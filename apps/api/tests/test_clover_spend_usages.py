"""차감 사용처(`clover_spend_usages`)와 환급 행(`clover_spend_refunds`)의 제약, 그리고 `spend(usage=…)` 가 남기는 사용처.

CHECK 는 alembic 1.18.5 의 `alembic check` 가 비교하지 않아 아래 `IntegrityError` 행위 테스트가 유일한 검증이다 — 지우면
커버리지가 오히려 오르므로 커버리지로는 빠진 것을 알 수 없다.
"""

import uuid

import pytest
from sqlalchemy import func, insert, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from api.core.clover import CloverKind, SpendUsage, spend, spend_in_new_transaction
from api.db.models.auth import User
from api.db.models.clover import (
    CloverLedger,
    CloverLot,
    CloverSpendAllocation,
    CloverSpendRefund,
    CloverSpendUsage,
    CloverSpendUsageKind,
)
from api.db.models.content import Content
from factories import _make_draft_content, _make_user, _make_user_with_clover_lot


async def _content(db: AsyncSession) -> Content:
    """작가 한 명의 작품 하나. 사용처가 가리키기만 하면 되므로 버전 없는 초안이다."""
    creator = _make_user()
    db.add(creator)
    await db.flush()
    return await _make_draft_content(db, creator_user_id=creator.id)


async def _usage_rows(db: AsyncSession, user_id: uuid.UUID) -> list[CloverSpendUsage]:
    return list(
        (await db.scalars(select(CloverSpendUsage).where(CloverSpendUsage.spender_user_id == user_id))).all()
    )


# ── 사용처 CHECK ─────────────────────────────────────────────────────────
async def _spend_ledger(db: AsyncSession) -> CloverLedger:
    user = _make_user()
    db.add(user)
    await db.flush()
    ledger = CloverLedger(user_id=user.id, amount=-10, balance_after=0, kind="chat_spend")
    db.add(ledger)
    await db.flush()
    return ledger


async def _insert_usage(db: AsyncSession, ledger: CloverLedger, content: Content, **overrides: object) -> None:
    """정상 채팅 사용처를 기본값으로, `overrides` 로 칸 하나를 틀어 넣는다."""
    values: dict[str, object] = {
        "spend_ledger_id": ledger.id,
        "usage_kind": "chat",
        "spender_user_id": ledger.user_id,
        "is_self_play": False,
        "content_id": content.id,
        "content_owner_user_id": content.creator_user_id,
        "chat_room_id": uuid.uuid4(),
        "novel_id": None,
        "publisher_user_id": None,
    }
    values.update(overrides)
    # 게시자 칸은 FK 라 실제 회원이어야 한다 — 표지 값 "spender" 를 지불자 id 로 바꾼다.
    if values.get("publisher_user_id") == "spender":
        values["publisher_user_id"] = ledger.user_id
    db.add(CloverSpendUsage(**values))
    await db.flush()


@pytest.mark.parametrize(
    "overrides",
    [
        pytest.param({}, id="chat"),
        pytest.param({"usage_kind": "novel", "novel_id": uuid.uuid4()}, id="novel-with-room"),
        pytest.param({"usage_kind": "novel", "novel_id": uuid.uuid4(), "chat_room_id": None}, id="novel-room-gone"),
        pytest.param(
            {"usage_kind": "novel_read", "novel_id": uuid.uuid4(), "chat_room_id": None, "publisher_user_id": "spender"},
            id="novel-read",
        ),
        pytest.param(
            {"usage_kind": "preview", "content_id": None, "content_owner_user_id": None, "chat_room_id": None},
            id="preview",
        ),
        pytest.param({"is_self_play": True}, id="self-play"),
        pytest.param({"spender_user_id": None}, id="spender-erased"),
    ],
)
async def test_valid_usage_is_accepted(db_session: AsyncSession, overrides: dict[str, object]) -> None:
    """대조군 — 아래 거부들이 셋업 탓이 아니라 그 값 탓임을 보인다. 방이 지워진 소설(방 id 없음)도 정상이다."""
    content = await _content(db_session)
    await _insert_usage(db_session, await _spend_ledger(db_session), content, **overrides)


async def test_insert_without_self_play_defaults_to_false(db_session: AsyncSession) -> None:
    """무중단 배포가 겹치는 동안 자기 플레이 칸을 모르는 옛 색의 노벨 구매 INSERT 가 칸을 빼고 보내도 거짓으로 들어간다."""
    content = await _content(db_session)
    ledger = await _spend_ledger(db_session)
    await db_session.execute(
        insert(CloverSpendUsage).values(
            spend_ledger_id=ledger.id,
            usage_kind="novel_read",
            spender_user_id=ledger.user_id,
            content_id=content.id,
            content_owner_user_id=content.creator_user_id,
            novel_id=uuid.uuid4(),
            publisher_user_id=ledger.user_id,
        )
    )

    stored = await db_session.scalar(
        select(CloverSpendUsage.is_self_play).where(CloverSpendUsage.spend_ledger_id == ledger.id)
    )
    assert stored is False


@pytest.mark.parametrize(
    ("overrides", "constraint"),
    [
        pytest.param({"usage_kind": "image"}, "ck_clover_spend_usages_kind", id="unknown-kind"),
        pytest.param(
            {"usage_kind": "preview", "chat_room_id": None},
            "ck_clover_spend_usages_preview_has_no_content",
            id="preview-with-content",
        ),
        pytest.param(
            {"content_id": None, "content_owner_user_id": None},
            "ck_clover_spend_usages_preview_has_no_content",
            id="chat-without-content",
        ),
        pytest.param(
            {"usage_kind": "preview", "content_id": None, "chat_room_id": None},
            "ck_clover_spend_usages_owner_with_content",
            id="owner-without-content",
        ),
        pytest.param({"chat_room_id": None}, "ck_clover_spend_usages_chat_has_room", id="chat-without-room"),
        pytest.param({"usage_kind": "novel"}, "ck_clover_spend_usages_novel_has_novel", id="novel-without-novel"),
        pytest.param({"novel_id": uuid.uuid4()}, "ck_clover_spend_usages_novel_has_novel", id="chat-with-novel"),
        pytest.param(
            {"usage_kind": "novel_read", "chat_room_id": None, "publisher_user_id": "spender"},
            "ck_clover_spend_usages_novel_has_novel",
            id="novel-read-without-novel",
        ),
        pytest.param(
            {"usage_kind": "novel_read", "novel_id": uuid.uuid4(), "chat_room_id": None},
            "ck_clover_spend_usages_publisher_for_novel_read",
            id="novel-read-without-publisher",
        ),
        pytest.param(
            {"usage_kind": "novel", "novel_id": uuid.uuid4(), "publisher_user_id": "spender"},
            "ck_clover_spend_usages_publisher_for_novel_read",
            id="novelize-with-publisher",
        ),
        pytest.param(
            {
                "usage_kind": "preview",
                "content_id": None,
                "content_owner_user_id": None,
                "chat_room_id": None,
                "is_self_play": True,
            },
            "ck_clover_spend_usages_self_play_has_owner",
            id="self-play-without-owner",
        ),
    ],
)
async def test_usage_check_constraints_reject(
    db_session: AsyncSession, overrides: dict[str, object], constraint: str
) -> None:
    """각 경우가 다른 CHECK 에 걸리지 않고 그 CHECK 하나에만 걸리도록 나머지 칸은 정상값으로 둔다."""
    content = await _content(db_session)
    ledger = await _spend_ledger(db_session)
    with pytest.raises(IntegrityError, match=constraint):
        await _insert_usage(db_session, ledger, content, **overrides)


async def test_one_spend_has_one_usage(db_session: AsyncSession) -> None:
    """원장 id 가 PK 라 차감 하나에 사용처는 하나뿐이다 — 같은 차감이 두 번 정산되지 않게 하는 마지막 그물."""
    content = await _content(db_session)
    ledger = await _spend_ledger(db_session)
    await _insert_usage(db_session, ledger, content)
    db_session.expunge_all()

    with pytest.raises(IntegrityError):
        await _insert_usage(db_session, ledger, content)


# ── 환급 행 CHECK ────────────────────────────────────────────────────────
async def test_refund_event_rejects_zero_amount(db_session: AsyncSession) -> None:
    """돌려준 양이 0 인 환급 행은 없다 — 환급이 이미 다 돌려받은 배분을 지날 때 행을 남기면 여기서 막힌다."""
    user = await _make_user_with_clover_lot(db_session, clover_balance=10)
    spent = await spend(db_session, user_id=user.id, amount=10, kind="chat_spend")
    assert spent is not None
    allocation_id = await db_session.scalar(
        select(CloverSpendAllocation.id).where(CloverSpendAllocation.spend_ledger_id == spent.ledger_id)
    )
    assert allocation_id is not None
    db_session.add(CloverSpendRefund(allocation_id=allocation_id, refund_ledger_id=spent.ledger_id, amount=1))
    await db_session.flush()

    db_session.add(CloverSpendRefund(allocation_id=allocation_id, refund_ledger_id=spent.ledger_id, amount=0))
    with pytest.raises(IntegrityError, match="ck_clover_spend_refunds_amount_positive"):
        await db_session.flush()


# ── spend(usage=…) ──────────────────────────────────────────────────────
async def test_spend_with_a_chat_usage_records_the_content_owner(db_session: AsyncSession) -> None:
    """채팅 차감의 사용처는 지불자와 별개로 작품 작가를 소유자로 남긴다. 깨지는 시나리오: 소유자를 지불자로 채우면
    남의 작품에서 쓴 클로버가 지불자 자신의 작품 매출로 잡힌다."""
    content = await _content(db_session)
    player = await _make_user_with_clover_lot(db_session, clover_balance=30)
    room_id = uuid.uuid4()

    spent = await spend(
        db_session,
        user_id=player.id,
        amount=10,
        kind="chat_spend",
        usage=SpendUsage("chat", content_id=content.id, chat_room_id=room_id),
    )

    assert spent is not None
    [usage] = await _usage_rows(db_session, player.id)
    assert (usage.spend_ledger_id, usage.usage_kind, usage.content_id, usage.chat_room_id, usage.novel_id) == (
        spent.ledger_id,
        "chat",
        content.id,
        room_id,
        None,
    )
    assert usage.content_owner_user_id == content.creator_user_id != player.id
    assert usage.is_self_play is False


async def test_spend_with_a_novel_usage_records_the_novel(db_session: AsyncSession) -> None:
    content = await _content(db_session)
    player = await _make_user_with_clover_lot(db_session, clover_balance=50)
    novel_id = uuid.uuid4()

    spent = await spend(
        db_session,
        user_id=player.id,
        amount=40,
        kind="novelize_spend",
        usage=SpendUsage("novel", content_id=content.id, novel_id=novel_id),
    )

    assert spent is not None
    [usage] = await _usage_rows(db_session, player.id)
    assert (usage.usage_kind, usage.content_owner_user_id, usage.chat_room_id, usage.novel_id, usage.is_self_play) == (
        "novel",
        content.creator_user_id,
        None,
        novel_id,
        False,
    )


@pytest.mark.parametrize(
    ("kind", "usage"),
    [
        pytest.param("chat_spend", "chat", id="chat"),
        pytest.param("novelize_spend", "novel", id="novel"),
    ],
)
async def test_spend_on_ones_own_content_is_recorded_as_self_play(
    db_session: AsyncSession, kind: CloverKind, usage: CloverSpendUsageKind
) -> None:
    """작가가 자기 작품에서 쓴 차감은 자기 플레이로 남는다. 깨지는 시나리오: 기록이 이 칸을 거짓으로 채우면 탈퇴로 지불자가
    끊긴 뒤 정산이 작가 자신의 사용을 매출로 센다."""
    owner = await _make_user_with_clover_lot(db_session, clover_balance=50)
    content = await _make_draft_content(db_session, creator_user_id=owner.id)

    spent = await spend(
        db_session,
        user_id=owner.id,
        amount=40,
        kind=kind,
        usage=SpendUsage(
            usage,
            content_id=content.id,
            chat_room_id=uuid.uuid4() if usage == "chat" else None,
            novel_id=uuid.uuid4() if usage == "novel" else None,
        ),
    )

    assert spent is not None
    [row] = await _usage_rows(db_session, owner.id)
    assert (row.content_owner_user_id, row.is_self_play) == (owner.id, True)


async def test_spend_with_a_preview_usage_points_to_no_content(db_session: AsyncSession) -> None:
    player = await _make_user_with_clover_lot(db_session, clover_balance=30)

    spent = await spend(db_session, user_id=player.id, amount=10, kind="chat_spend", usage=SpendUsage("preview"))

    assert spent is not None
    [usage] = await _usage_rows(db_session, player.id)
    assert (
        usage.spend_ledger_id,
        usage.usage_kind,
        usage.content_id,
        usage.content_owner_user_id,
        usage.is_self_play,
    ) == (spent.ledger_id, "preview", None, None, False)


async def test_preview_usage_with_a_content_is_rejected(db_session: AsyncSession) -> None:
    """작품이 있는데 미리보기로 넘긴 호출은 CHECK 에 걸려 실패한다. 깨지는 시나리오: 미리보기 갈래가 작품 id 를 버리면
    타인 작품에서 쓴 클로버가 소유자 없는 미리보기로 기록돼 정산에서 조용히 빠진다."""
    content = await _content(db_session)
    player = await _make_user_with_clover_lot(db_session, clover_balance=30)

    # 소유자 없이 작품만 들어가 CHECK 둘(미리보기는 작품 없음, 작품과 소유자는 함께)에 걸리고, 어느 쪽이 먼저 보고될지는
    # 정해져 있지 않아 제약 이름을 고르지 않는다.
    with pytest.raises(IntegrityError):
        await spend(
            db_session,
            user_id=player.id,
            amount=10,
            kind="chat_spend",
            usage=SpendUsage("preview", content_id=content.id),
        )


async def test_spend_without_usage_records_none(db_session: AsyncSession) -> None:
    """이미지 차감처럼 작품 맥락이 없는 차감은 사용처를 남기지 않는다."""
    player = await _make_user_with_clover_lot(db_session, clover_balance=30)

    assert await spend(db_session, user_id=player.id, amount=30, kind="image_spend") is not None

    assert await _usage_rows(db_session, player.id) == []


async def test_insufficient_spend_records_no_usage(db_session: AsyncSession) -> None:
    content = await _content(db_session)
    player = await _make_user_with_clover_lot(db_session, clover_balance=5)

    spent = await spend(
        db_session,
        user_id=player.id,
        amount=10,
        kind="chat_spend",
        usage=SpendUsage("chat", content_id=content.id, chat_room_id=uuid.uuid4()),
    )

    assert spent is None
    assert await _usage_rows(db_session, player.id) == []


async def test_spend_for_a_missing_content_raises(db_session: AsyncSession) -> None:
    """작품 행이 없으면 사용처 없이 차감만 남기지 않고 예외로 트랜잭션을 롤백시킨다(차감 전에 작품을 읽는 경로라
    도달하면 버그다)."""
    player = await _make_user_with_clover_lot(db_session, clover_balance=30)

    with pytest.raises(ValueError):
        await spend(
            db_session,
            user_id=player.id,
            amount=10,
            kind="chat_spend",
            usage=SpendUsage("chat", content_id=uuid.uuid4(), chat_room_id=uuid.uuid4()),
        )


async def test_spend_in_new_transaction_records_the_usage_in_its_commit(db_session: AsyncSession) -> None:
    """게이트 차감은 자기 세션에서 커밋한다 — 사용처가 그 세션에 함께 실려야 한다. 깨지는 시나리오: 래퍼가 `usage` 를
    `spend` 에 넘기지 않으면 채팅 차감 전부가 사용처 없이 남아 정산에서 빠진다."""
    content = await _content(db_session)
    player = await _make_user_with_clover_lot(db_session, clover_balance=30)
    # 테스트 트랜잭션과 같은 커넥션에 묶인 팩토리 — 래퍼의 커밋은 SAVEPOINT 만 확정하고 끝에서 함께 롤백된다.
    factory = async_sessionmaker(bind=db_session.bind, expire_on_commit=False)

    spent = await spend_in_new_transaction(
        factory,
        user_id=player.id,
        amount=10,
        kind="chat_spend",
        usage=SpendUsage("chat", content_id=content.id, chat_room_id=uuid.uuid4()),
    )

    assert spent is not None
    [usage] = await _usage_rows(db_session, player.id)
    assert (usage.spend_ledger_id, usage.content_owner_user_id) == (spent.ledger_id, content.creator_user_id)


async def test_spend_in_new_transaction_for_a_missing_content_rolls_back_the_charge(db_session: AsyncSession) -> None:
    """사용처를 못 남기면 차감도 남지 않는다 — 잔액·원장·배분이 그대로다. 깨지는 시나리오: 차감을 먼저 커밋하고 사용처를
    따로 넣으면, 사용처 실패가 사용처 없는 차감을 남겨 정산에서 빠진다."""
    player = await _make_user_with_clover_lot(db_session, clover_balance=30)
    # 테스트 트랜잭션과 같은 커넥션 위에 SAVEPOINT 로 여는 세션 — 래퍼 세션이 예외로 닫히면 그 SAVEPOINT 만 되돌아간다.
    factory = async_sessionmaker(
        bind=db_session.bind, join_transaction_mode="create_savepoint", expire_on_commit=False
    )

    with pytest.raises(ValueError):
        await spend_in_new_transaction(
            factory,
            user_id=player.id,
            amount=10,
            kind="chat_spend",
            usage=SpendUsage("chat", content_id=uuid.uuid4(), chat_room_id=uuid.uuid4()),
        )

    assert await db_session.scalar(select(User.clover_balance).where(User.id == player.id)) == 30
    ledger_ids = (await db_session.scalars(select(CloverLedger.id).where(CloverLedger.user_id == player.id))).all()
    assert ledger_ids == []
    assert (
        await db_session.scalar(
            select(func.count())
            .select_from(CloverSpendAllocation)
            .join(CloverLot, CloverLot.id == CloverSpendAllocation.lot_id)
            .where(CloverLot.user_id == player.id)
        )
        == 0
    )
