"""노벨 구매자 보호 — 정책 스위치(`novel_public_policy_v2_enabled`)가 켜졌을 때 산 사람이 무엇을 계속 읽고, 언제 무엇을
돌려받는가.

- 열람만 남는 경우: 게시자의 공개 거둠·게시자 정지·원작자 정지로 인한 원작 일괄 제한·판매된 소설 삭제(숨김). 새로 보이거나
  팔리지는 않지만 산 사람은 산 화·무료 화·목차를 계속 읽는다.
- 닫히는 경우: 노벨 이용제한·원작 자체 이용제한·원작 삭제·게시자 탈퇴. 산 사람은 410 이고 그 구매는 사유와 함께 환급된다
  — 닫히는 경우와 환급되는 경우가 같다. 다시 열려도 환급은 그대로이고 다시 살 수 있다.
- 판매된 소설을 지우면 숨긴다. 판매된 화가 든 마지막 묶음은 지울 수 없다. 숨긴 소설은 미환급 소장자가 사라지면 하루 한 번
  파기된다.

공개 소설은 `_make_public_novel`(원작 = 다른 회원의 공개 작품, 6화 + 2화 묶음, 전부 공개)로 만든다. 앞 5화가 무료라 6화가
첫 유료 화이고, 마지막 묶음은 7·8화다. 같은 `db_client` 에 회원 세션과 운영자 세션을 함께 싣는다(쿠키 이름이 다르다)."""

import uuid
from collections import Counter
from collections.abc import Awaitable, Callable, Sequence
from datetime import UTC, datetime, timedelta

import httpx
import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.config import settings
from api.db.models import User
from api.db.models.clover import CloverLedger
from api.db.models.content import Content, ModerationStatus
from api.db.models.moderation import (
    Appeal,
    AppealStatus,
    AppealTargetKind,
    ModerationAction,
    Report,
    ReportReasonCategory,
    ReportStatus,
)
from api.db.models.novel import (
    Novel,
    NovelChapter,
    NovelChapterPublication,
    NovelChapterRevision,
    NovelPublication,
    NovelPurchase,
    NovelReport,
)
from api.novelize.hidden_purge import purge_hidden_novels
from factories import (
    PublicNovel,
    _add_batch,
    _allow_novelize,
    _clear_llm_override,
    _create_admin,
    _login_as,
    _login_as_admin,
    _make_public_novel,
    _make_user,
    _make_user_with_clover_lot,
    _NeverCalledLLMClient,
    _novel_setup,
    _override_llm_client,
    _room_messages,
)


@pytest.fixture(autouse=True)
def _switches_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "novel_public_enabled", True)
    monkeypatch.setattr(settings, "novel_public_policy_v2_enabled", True)


async def _member(db_session: AsyncSession, balance: int = 100) -> uuid.UUID:
    user = await _make_user_with_clover_lot(db_session, clover_balance=balance)
    await db_session.commit()
    return user.id


async def _novel(db_session: AsyncSession, publisher: User | None = None) -> PublicNovel:
    if publisher is None:
        publisher = _make_user()
        db_session.add(publisher)
        await db_session.flush()
    novel = await _make_public_novel(db_session, publisher.id)
    await db_session.commit()
    return novel


def _path(novel: PublicNovel, ordinal: int) -> str:
    return f"/webnovels/{novel.novel_id}/chapters/{novel.chapter_ids[ordinal - 1]}"


async def _get(client: httpx.AsyncClient, path: str, *, as_user: uuid.UUID) -> httpx.Response:
    await _login_as(client, as_user)
    return await client.get(path)


async def _buy(client: httpx.AsyncClient, novel: PublicNovel, ordinal: int, *, as_user: uuid.UUID) -> httpx.Response:
    await _login_as(client, as_user)
    return await client.post(f"{_path(novel, ordinal)}/purchase", json={"expectedPrice": 30})


async def _bought(client: httpx.AsyncClient, novel: PublicNovel, ordinal: int, buyer: uuid.UUID) -> None:
    resp = await _buy(client, novel, ordinal, as_user=buyer)
    assert (resp.status_code, resp.json()["charged"]) == (200, 30), resp.text


async def _listed_ids(client: httpx.AsyncClient, *, as_user: uuid.UUID) -> list[str]:
    resp = await _get(client, "/webnovels", as_user=as_user)
    assert resp.status_code == 200
    return [item["id"] for item in resp.json()["items"]]


async def _balance(db_session: AsyncSession, user_id: uuid.UUID) -> int:
    balance = await db_session.scalar(
        sa.select(User.clover_balance).where(User.id == user_id).execution_options(populate_existing=True)
    )
    assert balance is not None
    return balance


async def _ledger(db_session: AsyncSession, user_id: uuid.UUID) -> list[tuple[str, int]]:
    rows = await db_session.execute(
        sa.select(CloverLedger.kind, CloverLedger.amount)
        .where(CloverLedger.user_id == user_id)
        .order_by(CloverLedger.created_at, CloverLedger.amount)
    )
    return [(kind, amount) for kind, amount in rows.tuples()]


async def _purchases(db_session: AsyncSession, buyer_id: uuid.UUID) -> Sequence[NovelPurchase]:
    return (
        await db_session.scalars(
            sa.select(NovelPurchase)
            .where(NovelPurchase.buyer_user_id == buyer_id)
            .order_by(NovelPurchase.chapter_ordinal, NovelPurchase.created_at)
            .execution_options(populate_existing=True)
        )
    ).all()


def _refunds(purchases: Sequence[NovelPurchase]) -> list[tuple[int, int | None, str | None]]:
    return [(p.chapter_ordinal, p.refunded_amount, p.refund_reason) for p in purchases]


async def _notifications(client: httpx.AsyncClient, user_id: uuid.UUID) -> list[dict[str, object]]:
    await _login_as(client, user_id)
    resp = await client.get("/notifications")
    assert resp.status_code == 200
    items: list[dict[str, object]] = resp.json()["items"]
    return items


async def _as_admin(client: httpx.AsyncClient, db_session: AsyncSession) -> None:
    admin = await _create_admin(db_session)
    await db_session.commit()
    await _login_as_admin(client, admin)


async def _creator_id(db_session: AsyncSession, novel: PublicNovel) -> uuid.UUID:
    creator = await db_session.scalar(sa.select(Content.creator_user_id).where(Content.id == novel.content_id))
    assert creator is not None
    return creator


async def _hide_in_db(db_session: AsyncSession, novel_id: uuid.UUID) -> None:
    """판매된 소설 삭제가 남기는 모양을 DB 로 만든다 — 숨김 시각, 방 칸 비움, 공개 거둠."""
    await db_session.execute(
        sa.update(Novel).where(Novel.id == novel_id).values(hidden_at=sa.func.now(), chat_room_id=None)
    )
    await db_session.execute(
        sa.update(NovelPublication).where(NovelPublication.novel_id == novel_id).values(visibility="withdrawn")
    )
    await db_session.commit()


async def _novel_exists(db_session: AsyncSession, novel_id: uuid.UUID) -> bool:
    return await db_session.scalar(sa.select(Novel.id).where(Novel.id == novel_id)) is not None


# ── 열람만 남는 경우 ─────────────────────────────────────────────────────────
Keep = Callable[[httpx.AsyncClient, AsyncSession, PublicNovel], Awaitable[None]]


async def _withdraw(_client: httpx.AsyncClient, db: AsyncSession, novel: PublicNovel) -> None:
    await db.execute(
        sa.update(NovelPublication).where(NovelPublication.novel_id == novel.novel_id).values(visibility="withdrawn")
    )
    await db.commit()


async def _suspend_publisher(_client: httpx.AsyncClient, db: AsyncSession, novel: PublicNovel) -> None:
    await db.execute(sa.update(User).where(User.id == novel.publisher_id).values(suspended_at=sa.func.now()))
    await db.commit()


async def _restrict_source_by_suspension(_client: httpx.AsyncClient, db: AsyncSession, novel: PublicNovel) -> None:
    await db.execute(
        sa.update(Content)
        .where(Content.id == novel.content_id)
        .values(moderation_status=ModerationStatus.RESTRICTED, restricted_by_suspension=True)
    )
    await db.commit()


async def _delete_sold_novel(client: httpx.AsyncClient, _db: AsyncSession, novel: PublicNovel) -> None:
    await _login_as(client, novel.publisher_id)
    assert (await client.delete(f"/novels/{novel.novel_id}")).status_code == 204


_KEEPS = [
    pytest.param(_withdraw, id="withdrawn"),
    pytest.param(_suspend_publisher, id="publisher-suspended"),
    pytest.param(_restrict_source_by_suspension, id="source-restricted-by-creator-suspension"),
    pytest.param(_delete_sold_novel, id="sold-novel-deleted"),
]


@pytest.mark.parametrize("keep", _KEEPS)
async def test_an_owner_keeps_reading_what_was_bought_while_the_novel_leaves_the_list_and_the_shop(
    db_client: httpx.AsyncClient, db_session: AsyncSession, keep: Keep
) -> None:
    """공개 거둠·게시자 정지·원작자 정지 일괄 제한·판매된 소설 삭제 뒤에도 6화를 산 사람은 6화를 그대로 읽는다. 노벨은 목록에서
    빠지고, 산 사람을 포함해 누구도 7화를 새로 살 수 없다(404). 깨지는 시나리오: 게시자 사정으로 산 사람이 산 화를 잃거나,
    목록에서 빠진 노벨이 구매 주소로는 계속 팔린다."""
    novel = await _novel(db_session)
    buyer, stranger = await _member(db_session), await _member(db_session)
    await _bought(db_client, novel, 6, buyer)

    await keep(db_client, db_session, novel)

    chapter = await _get(db_client, _path(novel, 6), as_user=buyer)
    assert chapter.status_code == 200, chapter.text
    assert (chapter.json()["access"], chapter.json()["paragraphs"]) == ("owned", ["6화 본문"])
    assert await _listed_ids(db_client, as_user=stranger) == []
    assert (await _buy(db_client, novel, 7, as_user=stranger)).status_code == 404
    assert (await _buy(db_client, novel, 7, as_user=buyer)).status_code == 404
    assert await _balance(db_session, buyer) == 70


@pytest.mark.parametrize("keep", _KEEPS)
async def test_an_owner_also_reads_the_free_chapters_and_the_contents_of_a_novel_no_longer_on_sale(
    db_client: httpx.AsyncClient, db_session: AsyncSession, keep: Keep
) -> None:
    """열람만 남은 노벨에서 산 사람은 작품 정보(목차, 판매 중지 표시)와 무료 화를 읽는다 — 사지 않은 유료 화는 목차에 잠김으로
    보인다. 사지 않은 독자에게는 작품 정보·무료 화 모두 지금처럼 이유 없는 404 다. 깨지는 시나리오: 6화를 산 사람이 1~5화를
    못 읽어 이어 읽기가 끊기거나, 판매가 멈춘 노벨이 남에게 다시 보인다."""
    novel = await _novel(db_session)
    buyer, stranger = await _member(db_session), await _member(db_session)
    await _bought(db_client, novel, 6, buyer)

    await keep(db_client, db_session, novel)

    detail = await _get(db_client, f"/webnovels/{novel.novel_id}", as_user=buyer)
    free = await db_client.get(_path(novel, 1))
    assert detail.status_code == 200, detail.text
    body = detail.json()
    assert body.get("salesStopped") is True
    assert [c["access"] for c in body["chapters"]] == ["free"] * 5 + ["owned", "locked", "locked"]
    assert (free.status_code, free.json().get("paragraphs")) == (200, ["1화 본문"])
    stranger_detail = await _get(db_client, f"/webnovels/{novel.novel_id}", as_user=stranger)
    stranger_free = await db_client.get(_path(novel, 1))
    assert (stranger_detail.status_code, stranger_free.status_code) == (404, 404)


# ── 닫히는 경우 = 환급되는 경우 ────────────────────────────────────────────────
Close = Callable[[httpx.AsyncClient, AsyncSession, PublicNovel], Awaitable[None]]


async def _restrict_novel(client: httpx.AsyncClient, db: AsyncSession, novel: PublicNovel) -> None:
    await _as_admin(client, db)
    resp = await client.post(
        f"/admin/novels/{novel.novel_id}/moderation", json={"action": "restrict", "adminComment": "운영정책 위반"}
    )
    assert resp.status_code == 200, resp.text


async def _restrict_novel_by_report(client: httpx.AsyncClient, db: AsyncSession, novel: PublicNovel) -> None:
    report = await _novel_report(db, novel)
    await _as_admin(client, db)
    resp = await client.post(
        f"/admin/novel-reports/{report}/actions", json={"action": "restrict", "adminComment": "운영정책 위반"}
    )
    assert resp.status_code == 200, resp.text


async def _act_on_source(client: httpx.AsyncClient, db: AsyncSession, novel: PublicNovel, action: str) -> None:
    await _as_admin(client, db)
    resp = await client.post(
        f"/admin/contents/{novel.content_id}/action", json={"action": action, "reasonCategory": "spam"}
    )
    assert resp.status_code == 200, resp.text


async def _restrict_source(client: httpx.AsyncClient, db: AsyncSession, novel: PublicNovel) -> None:
    await _act_on_source(client, db, novel, "restrict")


async def _delete_source(client: httpx.AsyncClient, db: AsyncSession, novel: PublicNovel) -> None:
    await _act_on_source(client, db, novel, "delete")


async def _act_on_source_report(client: httpx.AsyncClient, db: AsyncSession, novel: PublicNovel, action: str) -> None:
    reporter = await _member(db)
    report = Report(
        reporter_user_id=reporter,
        content_id=novel.content_id,
        reason_category=ReportReasonCategory.SPAM,
        status=ReportStatus.PENDING,
    )
    db.add(report)
    await db.commit()
    await _as_admin(client, db)
    resp = await client.post(f"/admin/reports/{report.id}/action", json={"action": action})
    assert resp.status_code == 200, resp.text


async def _restrict_source_by_report(client: httpx.AsyncClient, db: AsyncSession, novel: PublicNovel) -> None:
    await _act_on_source_report(client, db, novel, "restrict")


async def _delete_source_by_report(client: httpx.AsyncClient, db: AsyncSession, novel: PublicNovel) -> None:
    await _act_on_source_report(client, db, novel, "delete")


async def _restrict_again_while_creator_suspended(client: httpx.AsyncClient, db: AsyncSession, novel: PublicNovel) -> None:
    """원작자를 정지해 원작이 정지 표식과 함께 제한된 뒤, 운영자가 같은 원작을 직접 다시 제한한다(표식이 내려간다)."""
    await _as_admin(client, db)
    creator = await _creator_id(db, novel)
    suspended = await client.post(f"/admin/users/{creator}/suspend", json={"reasonCategory": "spam"})
    assert suspended.status_code == 200, suspended.text
    await _act_on_source(client, db, novel, "restrict")


async def _novel_report(db: AsyncSession, novel: PublicNovel) -> uuid.UUID:
    reporter = await _member(db)
    report = NovelReport(
        reporter_user_id=reporter,
        publisher_user_id=novel.publisher_id,
        novel_id=novel.novel_id,
        reason_category=ReportReasonCategory.SPAM,
        status=ReportStatus.PENDING,
        evidence_title="공개 제목",
        evidence_synopsis="소개",
        evidence_expires_at=datetime.now(UTC) + timedelta(days=1),
    )
    db.add(report)
    await db.commit()
    return report.id


_CLOSES = [
    pytest.param(_restrict_novel, "novel_restricted", "restricted", id="novel-restricted"),
    pytest.param(_restrict_novel_by_report, "novel_restricted", "restricted", id="novel-report-restrict"),
    pytest.param(_restrict_source, "source_restricted", "source_unavailable", id="source-restricted"),
    pytest.param(_delete_source, "source_deleted", "source_unavailable", id="source-deleted"),
    pytest.param(_restrict_source_by_report, "source_restricted", "source_unavailable", id="source-report-restrict"),
    pytest.param(_delete_source_by_report, "source_deleted", "source_unavailable", id="source-report-delete"),
    pytest.param(
        _restrict_again_while_creator_suspended,
        "source_restricted",
        "source_unavailable",
        id="source-restricted-again-during-creator-suspension",
    ),
]


@pytest.mark.parametrize(("close", "refund_reason", "_ended"), _CLOSES)
async def test_every_closing_write_refunds_each_purchase_with_its_reason(
    db_client: httpx.AsyncClient, db_session: AsyncSession, close: Close, refund_reason: str, _ended: str
) -> None:
    """노벨 이용제한(직접·신고 처리)·원작 이용제한·원작 삭제(직접·신고 처리)·원작자 정지 중의 재제한, 어느 쓰기 지점으로
    닫아도 산 사람은 410 이고 그 구매가 모두 사유와 함께 환급돼 잔액이 산 전으로 돌아간다. 깨지는 시나리오: 쓰기 지점 하나가
    환급을 빠뜨려 산 사람이 클로버를 잃은 채 읽지 못한다."""
    novel = await _novel(db_session)
    buyer = await _member(db_session)
    await _bought(db_client, novel, 6, buyer)
    await _bought(db_client, novel, 7, buyer)

    await close(db_client, db_session, novel)

    assert (await _get(db_client, _path(novel, 6), as_user=buyer)).status_code == 410
    assert _refunds(await _purchases(db_session, buyer)) == [(6, 30, refund_reason), (7, 30, refund_reason)]
    assert await _balance(db_session, buyer) == 100


@pytest.mark.parametrize(("close", "_refund_reason", "ended"), _CLOSES[:4])
async def test_a_refunded_owner_is_told_the_closing_reason_and_what_came_back(
    db_client: httpx.AsyncClient, db_session: AsyncSession, close: Close, _refund_reason: str, ended: str
) -> None:
    """닫힘 환급을 받은 사람의 410 이유는 "지워졌다"가 아니라 닫힌 이유(노벨 이용제한 → `restricted`, 원작 제한·삭제 →
    `source_unavailable`)이고 돌려준 클로버를 싣는다 — 화는 그 화 몫, 작품 정보는 소설 전체 몫이다. 사지 않은 사람은 이유 없는
    404 다. 깨지는 시나리오: 환급 행이 있다고 무조건 "게시자가 지웠다"로 안내되거나, 돌려준 양이 빠진다."""
    novel = await _novel(db_session)
    buyer, stranger = await _member(db_session), await _member(db_session)
    await _bought(db_client, novel, 6, buyer)
    await _bought(db_client, novel, 7, buyer)

    await close(db_client, db_session, novel)

    chapter = await _get(db_client, _path(novel, 6), as_user=buyer)
    detail = await db_client.get(f"/webnovels/{novel.novel_id}")
    assert (chapter.status_code, chapter.json()["detail"]) == (
        410,
        {"code": "NOVEL_READING_ENDED", "reason": ended, "refundedAmount": 30},
    )
    assert (detail.status_code, detail.json()["detail"]) == (
        410,
        {"code": "NOVEL_READING_ENDED", "reason": ended, "refundedAmount": 60},
    )
    as_stranger = await _get(db_client, _path(novel, 6), as_user=stranger)
    assert as_stranger.status_code == 404
    assert "reason" not in as_stranger.json()["detail"]


async def test_restricting_a_novel_refunds_every_buyer_once_and_lifting_keeps_the_refunds(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """노벨 이용제한은 모든 미환급 구매를 환급하고 구매자마다 알림 하나(화 수·클로버 수·사유)를 보낸다. 해제해도 환급을
    되돌리지 않는다. 깨지는 시나리오: 한 구매자의 두 화 환급이 알림 둘로 쌓이거나, 해제가 돌려준 클로버를 다시 깎는다."""
    novel = await _novel(db_session)
    first, second = await _member(db_session), await _member(db_session)
    await _bought(db_client, novel, 6, first)
    await _bought(db_client, novel, 7, first)
    await _bought(db_client, novel, 8, second)

    await _restrict_novel(db_client, db_session, novel)
    lifted = await db_client.post(
        f"/admin/novels/{novel.novel_id}/moderation", json={"action": "lift", "adminComment": "오인 조치"}
    )

    assert lifted.status_code == 200, lifted.text
    assert (await _balance(db_session, first), await _balance(db_session, second)) == (100, 100)
    assert _refunds(await _purchases(db_session, first)) == [(6, 30, "novel_restricted"), (7, 30, "novel_restricted")]
    [notice] = await _notifications(db_client, first)
    assert (notice["type"], notice["novelRefund"], notice.get("novelRefundReason")) == (
        "novel-purchase-refund",
        {"chapterCount": 2, "cloverAmount": 60},
        "novel_restricted",
    )
    [notice] = await _notifications(db_client, second)
    assert (notice["novelRefund"], notice.get("novelRefundReason")) == (
        {"chapterCount": 1, "cloverAmount": 30},
        "novel_restricted",
    )


async def test_a_report_on_an_already_restricted_novel_moves_no_clover(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """신고 처리의 이용제한은 직접 이용제한과 같이 환급하고, 이미 이용제한된 노벨의 신고를 다시 이용제한으로 처리해도(처리는
    된다) 돌려줄 것이 없어 원장·알림이 늘지 않는다. 깨지는 시나리오: 같은 노벨의 신고를 처리할 때마다 환급이 다시 돌아
    이중 환급되거나 환급 초과 오류로 처리가 500 이 된다."""
    novel = await _novel(db_session)
    buyer = await _member(db_session)
    await _bought(db_client, novel, 6, buyer)
    await _restrict_novel_by_report(db_client, db_session, novel)
    after_first = await _ledger(db_session, buyer)

    await _restrict_novel_by_report(db_client, db_session, novel)

    assert after_first == [("novel_read_spend", -30), ("novel_read_refund", 30)]
    assert await _ledger(db_session, buyer) == after_first
    assert len(await _notifications(db_client, buyer)) == 1


_SOURCE_ACTIONS = [
    pytest.param(_restrict_source, "source_restricted", id="restrict"),
    pytest.param(_delete_source, "source_deleted", id="delete"),
    pytest.param(_restrict_source_by_report, "source_restricted", id="report-restrict"),
    pytest.param(_delete_source_by_report, "source_deleted", id="report-delete"),
]


@pytest.mark.parametrize(("act", "reason"), _SOURCE_ACTIONS)
async def test_closing_a_source_refunds_every_novel_made_from_it_even_withdrawn_or_hidden_ones(
    db_client: httpx.AsyncClient, db_session: AsyncSession, act: Close, reason: str
) -> None:
    """원작을 직접·신고 처리로 제한하거나 지우면 그 원작으로 만든 소설 전부의 구매가 환급된다 — 공개 중인 것, 게시자가 거둔
    것, 판매 뒤 지워 숨긴 것까지. 깨지는 시나리오: 목록에서 이미 빠진 소설의 소장자는 열람이 닫혔는데 환급에서 빠진다."""
    public = await _novel(db_session)
    withdrawn, hidden = await _novel(db_session), await _novel(db_session)
    await db_session.execute(
        sa.update(Novel).where(Novel.id.in_([withdrawn.novel_id, hidden.novel_id])).values(content_id=public.content_id)
    )
    await db_session.commit()
    buyers = [await _member(db_session) for _ in range(3)]
    for novel, buyer in zip((public, withdrawn, hidden), buyers, strict=True):
        await _bought(db_client, novel, 6, buyer)
    await _withdraw(db_client, db_session, withdrawn)
    await _hide_in_db(db_session, hidden.novel_id)

    await act(db_client, db_session, public)

    for buyer in buyers:
        assert _refunds(await _purchases(db_session, buyer)) == [(6, 30, reason)]
        assert await _balance(db_session, buyer) == 100


async def test_rejecting_a_source_report_refunds_nothing(db_client: httpx.AsyncClient, db_session: AsyncSession) -> None:
    """원작 신고를 반려하면 원작 상태가 그대로이므로 환급도 없다. 깨지는 시나리오: 신고 처리 경로에 붙인 환급이 처리 종류를
    가리지 않아 반려에도 돌아간다."""
    novel = await _novel(db_session)
    buyer = await _member(db_session)
    await _bought(db_client, novel, 6, buyer)

    await _act_on_source_report(db_client, db_session, novel, "reject")

    assert _refunds(await _purchases(db_session, buyer)) == [(6, None, None)]
    assert (await _get(db_client, _path(novel, 6), as_user=buyer)).status_code == 200


async def test_creator_suspension_keeps_owners_reading_until_the_source_is_restricted_again(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """원작자 정지로 원작이 일괄 제한되면 환급하지 않고 산 사람은 계속 읽는다. 정지 중에 운영자가 같은 원작을 직접 다시 제한해
    정지 표식이 내려가면 그때 원작 자체 제재로 보고 환급한다. 깨지는 시나리오: 정지 일괄 제한에 환급해 정지 해제 뒤 다시 열린
    화를 산 사람이 다시 사야 하거나, 표식이 내려간 재제한에서 환급이 빠진다."""
    novel = await _novel(db_session)
    buyer = await _member(db_session)
    await _bought(db_client, novel, 6, buyer)
    await _as_admin(db_client, db_session)
    creator = await _creator_id(db_session, novel)
    assert (await db_client.post(f"/admin/users/{creator}/suspend", json={"reasonCategory": "spam"})).status_code == 200

    during_suspension = await _get(db_client, _path(novel, 6), as_user=buyer)
    kept = _refunds(await _purchases(db_session, buyer))
    await _act_on_source(db_client, db_session, novel, "restrict")

    assert during_suspension.status_code == 200, during_suspension.text
    assert kept == [(6, None, None)]
    assert _refunds(await _purchases(db_session, buyer)) == [(6, 30, "source_restricted")]
    assert (await _get(db_client, _path(novel, 6), as_user=buyer)).status_code == 410


async def test_an_accepted_appeal_reopens_the_source_without_taking_the_refund_back(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """원작 제한으로 환급받은 뒤 원작자의 이의제기가 받아들여져 원작이 정상이 돼도 환급은 그대로이고, 다시 열린 화를 다시 사면
    한 번 차감되고 읽힌다. 깨지는 시나리오: 다시 열면서 환급을 회수하거나, 환급된 구매를 소장으로 보아 0 클로버 "소장" 응답
    뒤 잠긴 화면이 된다."""
    novel = await _novel(db_session)
    buyer = await _member(db_session)
    await _bought(db_client, novel, 6, buyer)
    await _restrict_source(db_client, db_session, novel)
    action = await db_session.scalar(
        sa.select(ModerationAction.id).where(ModerationAction.content_id == novel.content_id)
    )
    assert action is not None
    appeal = Appeal(
        user_id=await _creator_id(db_session, novel),
        target_kind=AppealTargetKind.MODERATION_ACTION,
        target_id=action,
        reason_text="오인 조치입니다",
        status=AppealStatus.PENDING,
    )
    db_session.add(appeal)
    await db_session.commit()

    accepted = await db_client.post(f"/admin/appeals/{appeal.id}/resolve", json={"verdict": "accepted"})
    rebought = await _buy(db_client, novel, 6, as_user=buyer)
    chapter = await db_client.get(_path(novel, 6))

    assert accepted.status_code == 200, accepted.text
    assert (rebought.status_code, rebought.json().get("charged")) == (200, 30)
    assert (chapter.status_code, chapter.json()["access"]) == (200, "owned")
    assert Counter(_refunds(await _purchases(db_session, buyer))) == Counter([(6, 30, "source_restricted"), (6, None, None)])
    assert await _balance(db_session, buyer) == 70


async def test_with_the_policy_switch_off_no_closing_write_refunds(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """정책 스위치가 꺼져 있으면 노벨 이용제한(직접·신고 처리)·원작 제한·원작 삭제 어느 것도 환급하지 않는다 — 지금 동작
    그대로다. 깨지는 시나리오: 약관 개정 전에 닫힘 환급이 먼저 돌아 약관과 다르게 클로버가 움직인다."""
    monkeypatch.setattr(settings, "novel_public_policy_v2_enabled", False)
    closes: list[Close] = [_restrict_novel, _restrict_novel_by_report, _restrict_source, _delete_source]
    buyers: list[uuid.UUID] = []
    for close in closes:
        novel = await _novel(db_session)
        buyer = await _member(db_session)
        await _bought(db_client, novel, 6, buyer)
        await close(db_client, db_session, novel)
        buyers.append(buyer)

    for buyer in buyers:
        assert _refunds(await _purchases(db_session, buyer)) == [(6, None, None)]
        assert await _balance(db_session, buyer) == 70


# ── 재구매 ──────────────────────────────────────────────────────────────────
async def _lift_novel(client: httpx.AsyncClient, novel: PublicNovel) -> None:
    resp = await client.post(
        f"/admin/novels/{novel.novel_id}/moderation", json={"action": "lift", "adminComment": "오인 조치"}
    )
    assert resp.status_code == 200, resp.text


async def test_after_a_refund_and_a_reopening_buying_again_charges_once_and_opens_the_chapter(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """이용제한으로 환급받은 화가 해제로 다시 열리면, 다시 사는 요청이 한 번 차감되고 그 화가 소장으로 읽힌다. 깨지는
    시나리오: 환급된 옛 구매를 소장으로 보아 0 클로버 "이미 소장" 응답을 주고, 화면은 잠긴 채 남는다."""
    novel = await _novel(db_session)
    buyer = await _member(db_session)
    await _bought(db_client, novel, 6, buyer)
    await _restrict_novel(db_client, db_session, novel)
    await _lift_novel(db_client, novel)

    rebought = await _buy(db_client, novel, 6, as_user=buyer)
    chapter = await db_client.get(_path(novel, 6))

    assert (rebought.status_code, rebought.json().get("charged"), rebought.json().get("balance")) == (200, 30, 70)
    assert (chapter.status_code, chapter.json()["access"], chapter.json()["paragraphs"]) == (200, "owned", ["6화 본문"])


async def test_restricting_again_after_reopening_refunds_only_the_purchase_made_since(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """이용제한 → 해제 → 다시 삼 → 다시 이용제한. 앞서 환급한 구매는 다시 환급하지 않고 다시 산 구매만 환급한다 — 원장에는 차감
    둘·환급 둘뿐이고 잔액은 처음으로 돌아간다. 깨지는 시나리오: 두 번째 이용제한이 이미 환급한 구매를 다시 환급해 산 것보다
    많이 돌려받는다."""
    novel = await _novel(db_session)
    buyer = await _member(db_session)
    await _bought(db_client, novel, 6, buyer)
    await _restrict_novel(db_client, db_session, novel)
    await _lift_novel(db_client, novel)
    await _bought(db_client, novel, 6, buyer)

    restricted_again = await db_client.post(
        f"/admin/novels/{novel.novel_id}/moderation", json={"action": "restrict", "adminComment": "다시 위반"}
    )

    assert restricted_again.status_code == 200, restricted_again.text
    assert sorted(await _ledger(db_session, buyer)) == sorted(
        [("novel_read_spend", -30), ("novel_read_refund", 30), ("novel_read_spend", -30), ("novel_read_refund", 30)]
    )
    assert _refunds(await _purchases(db_session, buyer)) == [(6, 30, "novel_restricted"), (6, 30, "novel_restricted")]
    assert await _balance(db_session, buyer) == 100


# ── 판매된 소설 삭제 = 숨김 ──────────────────────────────────────────────────
async def test_deleting_a_sold_novel_hides_it_from_its_author_and_keeps_it_for_the_owners(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """팔린 소설을 지우면 204 이고, 소설은 작가 목록·주소·공개 상태 조회에서 사라지며(404) 공개는 거둠, 방 칸은 빈다. 환급은
    없고 산 사람은 계속 읽는다. 깨지는 시나리오: 작가의 삭제 한 번으로 산 사람의 소장이 사라지거나, 숨긴 소설이 작가 화면에
    남아 다시 고쳐 공개된다."""
    novel = await _novel(db_session)
    buyer = await _member(db_session)
    await _bought(db_client, novel, 6, buyer)
    await _allow_novelize(db_session, monkeypatch, novel.publisher_id)
    await _login_as(db_client, novel.publisher_id)

    deleted = await db_client.delete(f"/novels/{novel.novel_id}")
    listed = (await db_client.get("/novels")).json()["items"]
    detail = await db_client.get(f"/novels/{novel.novel_id}")
    publication_status = await db_client.get(f"/novels/{novel.novel_id}/publication")

    assert deleted.status_code == 204
    assert [item["id"] for item in listed] == []
    assert (detail.status_code, publication_status.status_code) == (404, 404)
    row = await db_session.get(Novel, novel.novel_id, populate_existing=True)
    assert row is not None
    assert (row.hidden_at is not None, row.chat_room_id) == (True, None)
    publication = await db_session.get_one(NovelPublication, novel.novel_id, populate_existing=True)
    assert publication.visibility == "withdrawn"
    assert _refunds(await _purchases(db_session, buyer)) == [(6, None, None)]
    assert await _balance(db_session, buyer) == 70
    assert (await _get(db_client, _path(novel, 6), as_user=buyer)).status_code == 200


async def _sold_room_novel(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    """방에서 만든 소설에 6화를 넣어 공개하고 다른 회원이 6화를 산다. (방 id, 소설 id, 게시자 id)."""
    room, novel_id = await _novel_setup(db_client, db_session, monkeypatch, turns=3)
    messages = await _room_messages(db_session, room.room_id)
    chapters = await _add_batch(db_session, novel_id, room, messages[0], messages[-1], episodes=6)
    owner = (await db_session.get_one(Novel, novel_id)).user_id
    db_session.add(NovelPublication(novel_id=novel_id, visibility="public", title="공개 제목", synopsis="소개"))
    for chapter in chapters:
        revision = await db_session.scalar(
            sa.select(NovelChapterRevision.id).where(NovelChapterRevision.chapter_id == chapter.id)
        )
        assert revision is not None
        db_session.add(
            NovelChapterPublication(
                chapter_id=chapter.id, novel_id=novel_id, ordinal=chapter.ordinal, revision_id=revision
            )
        )
    await db_session.commit()
    buyer = await _member(db_session)
    await _login_as(db_client, buyer)
    resp = await db_client.post(
        f"/webnovels/{novel_id}/chapters/{chapters[5].id}/purchase", json={"expectedPrice": 30}
    )
    assert resp.status_code == 200, resp.text
    await _login_as(db_client, owner)
    return room.room_id, novel_id, owner


async def test_the_room_of_a_hidden_novel_can_start_a_new_novel(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """방에서 만든 팔린 소설을 지우면 숨겨지고 방 칸이 비어, 같은 방에서 새 소설을 만들 수 있고(201) 방의 소설 조회는 새
    소설을 준다. 숨긴 소설은 그대로 남아 있다. 깨지는 시나리오: 숨긴 소설이 방에 묶인 채 남아 "이미 있는 소설"로 되살아나
    작가가 다시 고치거나, 같은 방의 새 소설 만들기가 막힌다."""
    room_id, novel_id, _owner = await _sold_room_novel(db_client, db_session, monkeypatch)

    assert (await db_client.delete(f"/novels/{novel_id}")).status_code == 204
    created = await db_client.post(f"/chat-rooms/{room_id}/novel")
    room_novel = await db_client.get(f"/chat-rooms/{room_id}/novel")

    assert created.status_code == 201, created.text
    assert created.json()["id"] != str(novel_id)
    assert room_novel.json()["id"] == created.json()["id"]
    hidden = await db_session.get(Novel, novel_id, populate_existing=True)
    assert hidden is not None and hidden.hidden_at is not None


_AUTHOR_WRITES = [
    pytest.param("GET", "/novels/{novel}", None, id="detail"),
    pytest.param("PUT", "/novels/{novel}/notes", {"settingNotes": "메모"}, id="notes"),
    pytest.param("PATCH", "/novels/{novel}", {"title": "새 제목"}, id="novel-title"),
    pytest.param("PATCH", "/novels/{novel}/chapters/{chapter}", {"authorNote": "작가의 말"}, id="chapter"),
    pytest.param("POST", "/novels/{novel}/chapters", {"endMessageId": "{chapter}", "expectedCost": "40"}, id="generate"),
    pytest.param("POST", "/novels/{novel}/publication", {"chapterId": "{chapter}"}, id="publish"),
    pytest.param("POST", "/novels/{novel}/publication/withdraw", None, id="withdraw"),
    pytest.param("DELETE", "/novels/{novel}/batches/{batch}", None, id="last-batch"),
    pytest.param("DELETE", "/novels/{novel}", None, id="delete-again"),
]


@pytest.mark.parametrize(("method", "template", "payload"), _AUTHOR_WRITES)
async def test_a_hidden_novel_is_not_found_on_any_author_route(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    method: str,
    template: str,
    payload: dict[str, str] | None,
) -> None:
    """숨긴 소설은 작가에게 없는 소설이다 — 상세·설정 노트·제목·화 글·화 생성·공개·거두기·마지막 묶음 삭제·다시 삭제가 모두
    404 다. LLM 은 불리면 실패하는 가짜로 갈아 끼운다(화 생성이 404 보다 먼저 작업을 띄우면 그 자체로 실패한다). 깨지는
    시나리오: 작가가 숨긴 소설 주소를 기억해 고치고 다시 공개해, 지웠다고 안내한 글이 독자에게 다시 나간다."""
    novel = await _novel(db_session)
    await _hide_in_db(db_session, novel.novel_id)
    await _allow_novelize(db_session, monkeypatch, novel.publisher_id)
    await _login_as(db_client, novel.publisher_id)
    _override_llm_client(_NeverCalledLLMClient())
    fill = {"novel": str(novel.novel_id), "chapter": str(novel.chapter_ids[7]), "batch": str(novel.batch_ids[1])}
    body = {key: value.format(**fill) for key, value in payload.items()} if payload is not None else None
    try:
        resp = await db_client.request(method, template.format(**fill), json=body)
    finally:
        _clear_llm_override()

    assert resp.status_code == 404, resp.text
    assert await _novel_exists(db_session, novel.novel_id)


async def test_a_novel_with_no_remaining_buyer_is_really_deleted(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """팔린 적 없는 소설과, 산 사람이 모두 탈퇴한 소설의 삭제는 지금처럼 진짜로 지운다(숨기지 않는다). 깨지는 시나리오: 소장자가
    없는데도 숨겨 남겨 작가가 지운 글을 보관할 근거 없이 쌓는다."""
    unsold = await _novel(db_session)
    left = await _novel(db_session)
    leaving = await _member(db_session)
    await _bought(db_client, left, 6, leaving)
    await _login_as(db_client, leaving)
    assert (await db_client.delete("/me")).status_code == 204

    for novel in (unsold, left):
        await _login_as(db_client, novel.publisher_id)
        assert (await db_client.delete(f"/novels/{novel.novel_id}")).status_code == 204
        assert not await _novel_exists(db_session, novel.novel_id)


async def test_a_novel_whose_every_purchase_was_refunded_is_really_deleted_and_previewed_as_unsold(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """산 사람이 있었어도 그 구매가 모두 환급됐으면(노벨 이용제한 등) 계속 읽을 사람이 없으므로, 삭제 전 고지는 숨김이 아니라고
    알리고(`novelSold` 거짓) 삭제는 진짜로 지운다. 구매 행(거래 기록)은 남는다. 깨지는 시나리오: 읽을 사람이 없는데 "산 사람이
    계속 읽도록 숨깁니다"라고 안내하고, 작가가 지운 글이 다음 파기까지 남는다."""
    novel = await _novel(db_session)
    buyer = await _member(db_session)
    await _bought(db_client, novel, 6, buyer)
    await db_session.execute(
        sa.update(NovelPurchase)
        .where(NovelPurchase.novel_id == novel.novel_id)
        .values(refunded_at=sa.func.now(), refunded_amount=30, refund_reason="novel_restricted")
    )
    await db_session.commit()
    await _allow_novelize(db_session, monkeypatch, novel.publisher_id)
    await _login_as(db_client, novel.publisher_id)

    preview = (await db_client.get(f"/novels/{novel.novel_id}")).json()["purchaseRefunds"]
    deleted = await db_client.delete(f"/novels/{novel.novel_id}")

    assert (preview["novelSold"], preview["novelBuyerCount"]) == (False, 0)
    assert deleted.status_code == 204
    assert not await _novel_exists(db_session, novel.novel_id)
    assert _refunds(await _purchases(db_session, buyer)) == [(6, 30, "novel_restricted")]


async def test_a_hidden_novel_published_again_by_an_old_image_stays_out_of_the_list_and_the_shop(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """숨긴 소설이 공개 범위 `public` 으로 돌아와 있어도(숨김을 모르는 옛 이미지로 되돌린 동안 작가가 다시 공개) 독자 목록에
    없고 아무도 새로 살 수 없으며, 소장자는 산 화를 계속 읽는다. 깨지는 시나리오: 작가에게는 지운 소설인데 독자에게 다시
    팔리고, 작가는 관리하려 하면 404 를 받는다."""
    novel = await _novel(db_session)
    owner, newcomer = await _member(db_session), await _member(db_session)
    await _bought(db_client, novel, 6, owner)
    await _hide_in_db(db_session, novel.novel_id)
    await db_session.execute(
        sa.update(NovelPublication).where(NovelPublication.novel_id == novel.novel_id).values(visibility="public")
    )
    await db_session.commit()

    listed = await _listed_ids(db_client, as_user=newcomer)
    bought = await _buy(db_client, novel, 7, as_user=newcomer)
    kept = await _get(db_client, _path(novel, 6), as_user=owner)

    assert str(novel.novel_id) not in listed
    assert bought.status_code == 404, bought.text
    assert kept.status_code == 200


async def test_the_last_batch_cannot_be_deleted_while_one_of_its_chapters_is_sold(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """팔린 화(7화)가 든 마지막 묶음은 묶음 주소로도 옛 마지막 화 주소로도 지울 수 없고(409 `NOVEL_BATCH_SOLD`) 아무것도
    지우거나 환급하지 않는다. 팔린 화가 앞 묶음에만 있으면(6화) 마지막 묶음은 지운다. 깨지는 시나리오: 묶음 삭제로 산 화를
    지워 소설 삭제의 숨김을 우회한다."""
    sold = await _novel(db_session)
    earlier_only = await _novel(db_session)
    buyer = await _member(db_session)
    await _bought(db_client, sold, 7, buyer)
    await _bought(db_client, earlier_only, 6, buyer)
    for novel in (sold, earlier_only):
        await _allow_novelize(db_session, monkeypatch, novel.publisher_id)

    await _login_as(db_client, sold.publisher_id)
    by_batch = await db_client.delete(f"/novels/{sold.novel_id}/batches/{sold.batch_ids[1]}")
    by_chapter = await db_client.delete(f"/novels/{sold.novel_id}/chapters/{sold.chapter_ids[7]}")
    await _login_as(db_client, earlier_only.publisher_id)
    allowed = await db_client.delete(f"/novels/{earlier_only.novel_id}/batches/{earlier_only.batch_ids[1]}")

    for refused in (by_batch, by_chapter):
        assert refused.status_code == 409, refused.text
        assert refused.json()["detail"] == {"code": "NOVEL_BATCH_SOLD"}
    chapters = await db_session.scalar(
        sa.select(sa.func.count()).select_from(NovelChapter).where(NovelChapter.novel_id == sold.novel_id)
    )
    assert chapters == 8
    assert allowed.status_code == 204
    assert _refunds(await _purchases(db_session, buyer)) == [(6, None, None), (7, None, None)]
    assert await _balance(db_session, buyer) == 40


# ── 탈퇴 ────────────────────────────────────────────────────────────────────
async def test_a_withdrawing_publisher_refunds_every_buyer_including_those_of_hidden_novels(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """게시자가 탈퇴하면 그 사람의 소설(숨긴 소설 포함)이 지워지고 모든 구매가 사유 `publisher_withdrawn` 으로 환급되며
    구매자마다 알림이 하나씩 간다. 산 사람이 열면 410 `publisher_withdrawn` 과 돌려준 클로버를 받는다. 깨지는 시나리오: 게시자
    탈퇴로 산 화를 읽을 수 없게 됐는데 클로버는 돌아오지 않는다."""
    publisher = _make_user()
    db_session.add(publisher)
    await db_session.flush()
    public = await _novel(db_session, publisher)
    hidden = await _novel(db_session, publisher)
    first, second = await _member(db_session), await _member(db_session)
    await _bought(db_client, public, 6, first)
    await _bought(db_client, public, 7, first)
    await _bought(db_client, hidden, 6, second)
    await _hide_in_db(db_session, hidden.novel_id)

    await _login_as(db_client, publisher.id)
    assert (await db_client.delete("/me")).status_code == 204

    assert not await _novel_exists(db_session, public.novel_id)
    assert not await _novel_exists(db_session, hidden.novel_id)
    assert _refunds(await _purchases(db_session, first)) == [
        (6, 30, "publisher_withdrawn"),
        (7, 30, "publisher_withdrawn"),
    ]
    assert _refunds(await _purchases(db_session, second)) == [(6, 30, "publisher_withdrawn")]
    assert (await _balance(db_session, first), await _balance(db_session, second)) == (100, 100)
    [notice] = await _notifications(db_client, first)
    assert (notice["novelRefund"], notice.get("novelRefundReason")) == (
        {"chapterCount": 2, "cloverAmount": 60},
        "publisher_withdrawn",
    )
    ended = await _get(db_client, _path(public, 6), as_user=first)
    assert (ended.status_code, ended.json()["detail"]) == (
        410,
        {"code": "NOVEL_READING_ENDED", "reason": "publisher_withdrawn", "refundedAmount": 30},
    )


async def test_a_kakao_unlink_of_a_publisher_refunds_the_buyers_too(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """카카오 연결 끊기 알림으로 게시자가 파기돼도 탈퇴와 같이 구매자에게 환급한다. 깨지는 시나리오: 카카오 쪽에서 연결을
    끊어 탈퇴하면 환급을 건너뛴다(같은 파기의 두 입구)."""
    admin_key = "test-kakao-admin-key"
    monkeypatch.setattr(settings, "kakao_admin_key", admin_key)
    publisher = _make_user(kakao_id=f"kakao-{uuid.uuid4().hex[:12]}")
    db_session.add(publisher)
    await db_session.flush()
    novel = await _novel(db_session, publisher)
    buyer = await _member(db_session)
    await _bought(db_client, novel, 6, buyer)

    resp = await db_client.get(
        "/auth/kakao/unlink",
        params={"app_id": "1", "user_id": publisher.kakao_id, "referrer_type": "UNLINK_FROM_APPS"},
        headers={"Authorization": f"KakaoAK {admin_key}"},
    )

    assert resp.status_code == 200
    assert not await _novel_exists(db_session, novel.novel_id)
    assert _refunds(await _purchases(db_session, buyer)) == [(6, 30, "publisher_withdrawn")]
    assert await _balance(db_session, buyer) == 100


# ── 숨긴 소설 파기 ───────────────────────────────────────────────────────────
async def _hidden_novels_in_each_state(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> dict[str, uuid.UUID]:
    """숨긴 소설 셋(구매자 탈퇴·전부 환급·미환급 소장자 남음)과 숨기지 않은 소설 하나."""
    novels = {name: await _novel(db_session) for name in ("buyer_left", "all_refunded", "owner_left", "visible")}
    leaving, refunded, owner = await _member(db_session), await _member(db_session), await _member(db_session)
    await _bought(db_client, novels["buyer_left"], 6, leaving)
    await _bought(db_client, novels["all_refunded"], 6, refunded)
    await _bought(db_client, novels["owner_left"], 6, owner)
    await _login_as(db_client, leaving)
    assert (await db_client.delete("/me")).status_code == 204
    await db_session.execute(
        sa.update(NovelPurchase)
        .where(NovelPurchase.novel_id == novels["all_refunded"].novel_id)
        .values(refunded_at=sa.func.now(), refunded_amount=30, refund_reason="novel_restricted")
    )
    for name in ("buyer_left", "all_refunded", "owner_left"):
        await _hide_in_db(db_session, novels[name].novel_id)
    return {name: novel.novel_id for name, novel in novels.items()}


async def _purchase_count(db_session: AsyncSession, novel_ids: Sequence[uuid.UUID]) -> int:
    count = await db_session.scalar(
        sa.select(sa.func.count()).select_from(NovelPurchase).where(NovelPurchase.novel_id.in_(novel_ids))
    )
    return count or 0


async def test_the_daily_purge_destroys_only_hidden_novels_without_an_unrefunded_buyer(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """하루 한 번 파기는 미환급 구매자가 남지 않은 숨긴 소설(구매자가 모두 탈퇴, 모두 환급)만 지운다. 미환급 소장자가 남은
    숨긴 소설과 숨기지 않은 소설은 그대로이고, 구매 행(거래 기록 사본)은 하나도 지우지 않는다. 깨지는 시나리오: 아직 읽는
    사람이 있는 숨긴 소설을 지우거나, 소장이 끝난 숨긴 소설이 기한 없이 남는다."""
    ids = await _hidden_novels_in_each_state(db_client, db_session)
    purchases = await _purchase_count(db_session, list(ids.values()))

    purged = await purge_hidden_novels(db_session)

    assert purged == 2
    assert {name: await _novel_exists(db_session, novel_id) for name, novel_id in ids.items()} == {
        "buyer_left": False,
        "all_refunded": False,
        "owner_left": True,
        "visible": True,
    }
    assert await _purchase_count(db_session, list(ids.values())) == purchases == 3


async def test_running_the_purge_again_destroys_nothing(db_client: httpx.AsyncClient, db_session: AsyncSession) -> None:
    """두 번째 실행은 지울 것이 없다(0). 깨지는 시나리오: 같은 날 두 번 돈 파기가 남은 소설을 잘못 고르거나 이미 지운 소설에서
    오류로 멈춘다."""
    ids = await _hidden_novels_in_each_state(db_client, db_session)
    first = await purge_hidden_novels(db_session)

    again = await purge_hidden_novels(db_session)

    assert (first, again) == (2, 0)
    assert await _novel_exists(db_session, ids["owner_left"])
