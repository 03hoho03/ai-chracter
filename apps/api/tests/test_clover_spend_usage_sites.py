"""차감 지점마다 사용처가 남는가 — 채팅 방 세 경로 × 차감 갈래, 빌더 미리보기, 소설 작업 종류마다.

크리에이터 정산은 사용처에서 출발하므로 사용처 없는 `chat_spend`·`novelize_spend` 는 그대로 정산에서 빠진다. 그래서 각
경로를 실제로 태운 뒤 그 사용자의 차감 원장을 사용처에 LEFT JOIN 해 빠진 행이 없는지 보고, 남은 행이 작품·소유자·방·소설을
맞게 가리키는지 본다. 플레이어와 작가를 따로 만든다 — 같은 사람이면 소유자를 지불자로 잘못 적어도 값이 같아 보인다.

새 차감 경로가 생겨도 사용처를 빠뜨리지 않게 하는 마지막 그물은 `src/` 의 차감 호출을 구문 트리로 훑는 구조 테스트다.
"""

import ast
import uuid
import warnings
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest
import sqlalchemy as sa
from redis.exceptions import ConnectionError as RedisConnectionError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from api.chat.router import enforce_room_chat_charge
from api.chat.turn_lock import RoomTurnLock
from api.core import clover, rate_limit_gate
from api.core.clover import SpendUsage
from api.core.config import settings
from api.core.rate_limit_gate import charge_chat_turn
from api.db.models import Content, ModerationStatus, Novel, NovelChapterRevision, User
from api.db.models.chat import ChatMessage, ChatMessageRole, ChatRoom
from api.db.models.clover import CloverLedger, CloverSpendAllocation, CloverSpendUsage
from api.llm.chat_models import DEFAULT_CHAT_MODEL
from api.llm.client import LLMCallContext, LLMClient, LLMClientError, T
from api.novelize import router as novelize_router
from api.novelize import runner
from factories import (
    _add_chapter,
    _allow_chat_premium,
    _batch_output,
    _clear_llm_override,
    _FakeLLMClient,
    _get_genre,
    _login_as,
    _make_published_character,
    _make_user,
    _make_user_with_clover_lot,
    _NeverCalledLLMClient,
    _novel_setup,
    _override_llm_client,
    _room_messages,
)

_SRC = Path(__file__).resolve().parent.parent / "src"

# 소설 쪽은 정책 단가가 아니라 사용처 기록과 연쇄의 순사용(선차감 − 환급)을 보므로, 확인 금액·순사용을 고정 단가로 적는다.
pytestmark = pytest.mark.usefixtures("novel_prices_for_flow_tests")


@pytest.fixture(autouse=True)
def _identity_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    """본인인증 게이트는 설정이 있어야 켜진다. 기본은 꺼짐이고 미인증 갈래만 켠다(로컬 `.env` 값에 기대지 않는다)."""
    monkeypatch.setattr(settings, "portone_store_id", "store-test-0001")
    monkeypatch.setattr(settings, "portone_identity_channel_key", "identity-channel-test")
    monkeypatch.setattr(settings, "portone_api_secret", "api-secret-test")
    monkeypatch.setattr(settings, "identity_ci_hmac_key", "ci-key-test")
    monkeypatch.setattr(settings, "identity_gate_enabled", False)


def _factory(db: AsyncSession) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(bind=db.bind, expire_on_commit=False)


UsageRow = tuple[str, uuid.UUID | None, uuid.UUID | None, uuid.UUID | None, uuid.UUID | None, int]


async def _usages(db: AsyncSession, user_id: uuid.UUID) -> list[UsageRow]:
    """사용자의 사용처(종류, 작품, 소유자, 방, 소설, 그 차감 원장 금액)."""
    rows = await db.execute(
        sa.select(
            CloverSpendUsage.usage_kind,
            CloverSpendUsage.content_id,
            CloverSpendUsage.content_owner_user_id,
            CloverSpendUsage.chat_room_id,
            CloverSpendUsage.novel_id,
            CloverLedger.amount,
        )
        .join(CloverLedger, CloverLedger.id == CloverSpendUsage.spend_ledger_id)
        .where(CloverSpendUsage.spender_user_id == user_id)
    )
    return [tuple(row) for row in rows.all()]


async def _spends_without_usage(db: AsyncSession, user_id: uuid.UUID) -> list[str]:
    """사용처 없는 채팅·소설 차감 원장 행의 종류. 정산이 빠뜨리는 행이다."""
    rows = await db.scalars(
        sa.select(CloverLedger.kind)
        .outerjoin(CloverSpendUsage, CloverSpendUsage.spend_ledger_id == CloverLedger.id)
        .where(
            CloverLedger.user_id == user_id,
            CloverLedger.kind.in_(("chat_spend", "novelize_spend")),
            CloverSpendUsage.spend_ledger_id.is_(None),
        )
    )
    return list(rows.all())


async def _another_creator(db: AsyncSession) -> User:
    creator = _make_user()
    db.add(creator)
    await db.flush()
    return creator


# ── 채팅: 방 세 경로 × 차감 갈래 ─────────────────────────────────────────────
_SURFACES = ["send", "regenerate", "edit"]
_MODES = {
    # 일일 무료분을 다 쓴 Gemini 턴.
    "gemini": clover.CHAT_TURN_COST,
    # 본인인증 게이트에 걸린 회원의 Gemini 턴(무료분 0).
    "unverified": clover.CHAT_TURN_COST,
    "sonnet": clover.CHAT_TURN_COST_SONNET,
    "opus": clover.CHAT_TURN_COST_OPUS,
}


async def _paid_room_turn(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    *,
    player: User,
    content: Content,
    surface: str,
    mode: str,
) -> tuple[uuid.UUID, httpx.Response]:
    """`player` 가 `content` 로 방을 열고 무료 턴 하나를 보낸 뒤(재생성·편집 대상), `mode` 로만 낼 수 있게 바꾸고 `surface`
    턴을 보낸다. 방 id 와 그 응답을 돌려준다."""
    await _login_as(db_client, player.id)
    created = await db_client.post("/chat-rooms", json={"contentId": str(content.id), "contentType": "character"})
    assert created.status_code == 201, created.text
    room_id = uuid.UUID(created.json()["id"])
    _override_llm_client(_FakeLLMClient(tokens=["응", "답"]))
    try:
        assert (await db_client.post(f"/chat-rooms/{room_id}/messages", json={"content": "안녕"})).status_code == 200
        if mode == "gemini":
            monkeypatch.setattr(rate_limit_gate, "CHAT_DAILY_LIMIT", 0)
        elif mode == "unverified":
            monkeypatch.setattr(settings, "identity_gate_enabled", True)
        else:
            await db_session.execute(sa.update(ChatRoom).where(ChatRoom.id == room_id).values(chat_model=mode))
            await db_session.commit()
        if surface == "send":
            resp = await db_client.post(f"/chat-rooms/{room_id}/messages", json={"content": "다시 안녕"})
        elif surface == "regenerate":
            resp = await db_client.post(f"/chat-rooms/{room_id}/regenerate")
        else:
            message_id = await db_session.scalar(
                sa.select(ChatMessage.id).where(
                    ChatMessage.chat_room_id == room_id, ChatMessage.role == ChatMessageRole.USER
                )
            )
            resp = await db_client.patch(f"/chat-rooms/{room_id}/messages/{message_id}", json={"content": "고친 말"})
    finally:
        _clear_llm_override()
    return room_id, resp


@pytest.mark.parametrize("mode", list(_MODES))
@pytest.mark.parametrize("surface", _SURFACES)
async def test_a_paid_turn_in_another_creators_room_records_the_room_and_its_owner(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    surface: str,
    mode: str,
) -> None:
    """방 세 경로 모두, 차감 갈래(무료분 소진 뒤·미인증·Sonnet·Opus) 모두 한 차감에 사용처 하나가 남고, 소유자는 플레이어가
    아니라 작품 작가다."""
    creator = await _another_creator(db_session)
    content = await _make_published_character(
        db_session, creator_user_id=creator.id, genre_id=(await _get_genre(db_session)).id
    )
    player = await _make_user_with_clover_lot(
        db_session, clover_balance=1000, clover_spend_confirmed_on=clover.kst_today(datetime.now(UTC))
    )
    await db_session.commit()
    if mode in ("sonnet", "opus"):
        await _allow_chat_premium(db_session, monkeypatch, player.id)

    room_id, resp = await _paid_room_turn(
        db_client, db_session, monkeypatch, player=player, content=content, surface=surface, mode=mode
    )

    assert resp.status_code == 200, resp.text
    assert await _usages(db_session, player.id) == [("chat", content.id, creator.id, room_id, None, -_MODES[mode])]
    assert await _spends_without_usage(db_session, player.id) == []


async def test_a_paid_turn_in_ones_own_room_records_the_player_as_the_owner(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """자기 작품 방이면 소유자 = 지불자로 남는다. 자기 플레이를 빼는 판정은 정산이 이 두 칸을 비교해 한다."""
    player = await _make_user_with_clover_lot(
        db_session, clover_balance=100, clover_spend_confirmed_on=clover.kst_today(datetime.now(UTC))
    )
    content = await _make_published_character(
        db_session, creator_user_id=player.id, genre_id=(await _get_genre(db_session)).id
    )
    await db_session.commit()

    room_id, resp = await _paid_room_turn(
        db_client, db_session, monkeypatch, player=player, content=content, surface="send", mode="gemini"
    )

    assert resp.status_code == 200, resp.text
    assert await _usages(db_session, player.id) == [
        ("chat", content.id, player.id, room_id, None, -clover.CHAT_TURN_COST)
    ]


async def test_an_unverified_turn_charged_during_a_redis_outage_records_its_usage(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """버스트 검사가 Redis 장애로 실패해도 미인증 회원은 클로버로 낸다(무료로 통과시키지 않는다). 그 차감도 사용처를 남긴다."""
    monkeypatch.setattr(settings, "identity_gate_enabled", True)

    async def _down(*_args: Any, **_kwargs: Any) -> int:
        raise RedisConnectionError("down")

    monkeypatch.setattr(rate_limit_gate, "check_rate_limit", _down)
    creator = await _another_creator(db_session)
    content = await _make_published_character(
        db_session, creator_user_id=creator.id, genre_id=(await _get_genre(db_session)).id
    )
    player = await _make_user_with_clover_lot(
        db_session, clover_balance=100, clover_spend_confirmed_on=clover.kst_today(datetime.now(UTC))
    )
    room_id = uuid.uuid4()

    charge = await charge_chat_turn(
        player.id,
        db_session,
        _factory(db_session),
        model=DEFAULT_CHAT_MODEL,
        price=clover.CHAT_TURN_COST,
        usage=SpendUsage("chat", content_id=content.id, chat_room_id=room_id),
    )

    assert charge.source == "clover"
    assert await _usages(db_session, player.id) == [
        ("chat", content.id, creator.id, room_id, None, -clover.CHAT_TURN_COST)
    ]


async def test_a_paid_preview_turn_records_a_preview_usage_without_a_content(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """빌더 미리보기도 `chat_spend` 로 차감되지만 작품을 가리키지 않는 `preview` 로 남는다 — 정산 대상이 아니라는 표시이고,
    사용처 없는 차감 수(배포 겹침 감시)에 미리보기가 섞이지 않게 한다."""
    player = await _make_user_with_clover_lot(
        db_session, clover_balance=100, clover_spend_confirmed_on=clover.kst_today(datetime.now(UTC))
    )
    await db_session.commit()
    await _login_as(db_client, player.id)
    created = await db_client.post(
        "/preview-sessions",
        json={
            "name": "아리아",
            "oneLiner": "한 줄 소개",
            "thumbnailAssetId": None,
            "intro": "안녕하세요, 아리아예요",
            "exampleDialogues": [],
            "characterPrompt": "너는 아리아다.",
            "playguide": None,
            "situationalImages": [],
            "description": "상세 설명",
            "genreId": None,
            "target": None,
            "hashtags": [],
            "visibility": "private",
        },
    )
    assert created.status_code == 201, created.text
    monkeypatch.setattr(rate_limit_gate, "CHAT_DAILY_LIMIT", 0)
    _override_llm_client(_FakeLLMClient(tokens=["응", "답"]))
    try:
        resp = await db_client.post(
            f"/preview-sessions/{created.json()['previewSessionId']}/messages", json={"content": "안녕"}
        )
    finally:
        _clear_llm_override()

    assert resp.status_code == 200, resp.text
    assert await _usages(db_session, player.id) == [("preview", None, None, None, None, -clover.CHAT_TURN_COST)]
    assert await _spends_without_usage(db_session, player.id) == []


# ── 무료 턴: 사용처도, 그것을 위한 조회도 없다 ─────────────────────────────────
class _Statements:
    """테스트 커넥션에서 실행된 SQL 문. 게이트의 차감은 같은 커넥션에 묶인 자기 세션에서 돌아 함께 잡힌다."""

    def __init__(self) -> None:
        self.seen: list[str] = []

    def __call__(self, _conn: Any, _cursor: Any, statement: str, *_args: Any) -> None:
        self.seen.append(statement)

    def touching(self, table: str) -> list[str]:
        return [s for s in self.seen if f" {table} " in f" {s} ".replace("\n", " ").replace("(", " ")]


async def _gate_statements(db_session: AsyncSession, room_id: uuid.UUID, user_id: uuid.UUID) -> _Statements:
    """방 경로 게이트 하나를 부르고 그동안 나간 SQL 을 돌려준다. 작품 행을 세션에서 비워 두어, 게이트가 작품을 읽으면
    identity map 이 아니라 SELECT 로 드러나게 한다."""
    db_session.expunge_all()
    room = await db_session.get_one(ChatRoom, room_id)
    statements = _Statements()
    connection = (await db_session.connection()).sync_connection
    assert connection is not None
    sa.event.listen(connection, "before_cursor_execute", statements)
    try:
        await enforce_room_chat_charge(
            _turn_lock=RoomTurnLock(room_id=room_id, token=None, acquired_at=0.0),
            room=room,
            user_id=user_id,
            db=db_session,
            session_factory=_factory(db_session),
        )
    finally:
        sa.event.remove(connection, "before_cursor_execute", statements)
    return statements


async def test_a_free_turn_records_no_usage_and_reads_no_content(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """무료 턴은 원장 행이 없어 사용처도 없고, 작품 소유자를 미리 읽지도 않는다. 클로버를 낸 턴은 소유자를 사용처 INSERT
    한 문장 안에서 읽는다 — 따로 나가는 작품 조회가 없다."""
    creator = await _another_creator(db_session)
    content = await _make_published_character(
        db_session, creator_user_id=creator.id, genre_id=(await _get_genre(db_session)).id
    )
    player = await _make_user_with_clover_lot(
        db_session, clover_balance=100, clover_spend_confirmed_on=clover.kst_today(datetime.now(UTC))
    )
    await db_session.commit()
    await _login_as(db_client, player.id)
    created = await db_client.post("/chat-rooms", json={"contentId": str(content.id), "contentType": "character"})
    room_id = uuid.UUID(created.json()["id"])

    free = await _gate_statements(db_session, room_id, player.id)
    monkeypatch.setattr(rate_limit_gate, "CHAT_DAILY_LIMIT", 0)
    paid = await _gate_statements(db_session, room_id, player.id)

    assert (free.touching("contents"), free.touching("clover_spend_usages")) == ([], [])
    assert len(paid.touching("clover_spend_usages")) == 1
    assert paid.touching("contents") == paid.touching("clover_spend_usages")
    assert await _usages(db_session, player.id) == [
        ("chat", content.id, creator.id, room_id, None, -clover.CHAT_TURN_COST)
    ]


# ── 소설 작업 ─────────────────────────────────────────────────────────────────
@pytest.fixture
def enqueued(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[uuid.UUID]]:
    """작업을 띄우는 함수를 기록으로 바꾼다 — 여기서는 차감과 사용처만 보고 실행은 하지 않는다."""
    seen: list[uuid.UUID] = []

    async def record(_factory: Any, _llm: Any, job_id: uuid.UUID) -> None:
        seen.append(job_id)

    monkeypatch.setattr(novelize_router, "enqueue_job", record)
    monkeypatch.setattr(novelize_router, "enqueue_chain_job", record)
    _override_llm_client(_NeverCalledLLMClient())
    yield seen
    _clear_llm_override()


async def _hand_to_another_creator(db: AsyncSession, novel_id: uuid.UUID) -> tuple[Novel, User]:
    """소설 원작의 작가를 다른 회원으로 바꾼다 — 플레이어가 남의 작품으로 소설을 만드는 상태."""
    novel = await db.get_one(Novel, novel_id)
    creator = await _another_creator(db)
    await db.execute(sa.update(Content).where(Content.id == novel.content_id).values(creator_user_id=creator.id))
    await db.commit()
    return novel, creator


_NOVEL_JOBS = ["chapter", "chain", "regenerate", "ai_edit", "ai_edit_room_gone"]


@pytest.mark.parametrize("job", _NOVEL_JOBS)
async def test_each_novel_job_records_the_novel_its_room_and_the_works_owner(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    enqueued: list[uuid.UUID],
    job: str,
) -> None:
    """화 생성·연쇄(부모)·다시 만들기·AI 수정 모두 한 차감에 사용처 하나. 방을 지운 소설의 AI 수정은 방이 비고 원작은
    소설 행의 사본으로 그대로 남는다."""
    monkeypatch.setattr(settings, "novelize_chapter_max_turns", 2)
    room, novel_id = await _novel_setup(db_client, db_session, monkeypatch)
    # 연쇄는 묶음 둘 × 화 수 상한 3 × 40 = 240 을 미리 낸다.
    await clover.grant(db_session, user_id=room.user_id, amount=500, kind="admin_grant")
    await db_session.commit()
    novel, creator = await _hand_to_another_creator(db_session, novel_id)
    messages = await _room_messages(db_session, room.room_id)
    expected_room: uuid.UUID | None = room.room_id
    if job == "chapter":
        resp = await db_client.post(
            f"/novels/{novel_id}/chapters", json={"endMessageId": str(room.turns[1][1].id), "expectedCost": 40}
        )
    elif job == "chain":
        estimate = (await db_client.get(f"/novels/{novel_id}/chain-estimate")).json()["options"][0]
        resp = await db_client.post(
            f"/novels/{novel_id}/chain",
            json={"model": "gemini", "expectedCost": estimate["cost"], "maxBatches": estimate["batchCount"]},
        )
    else:
        chapter = await _add_chapter(db_session, novel_id, room, messages[0], room.turns[1][1])
        if job == "regenerate":
            resp = await db_client.post(f"/novels/{novel_id}/chapters/{chapter.id}/regenerate", json={"expectedCost": 40})
        else:
            if job == "ai_edit_room_gone":
                await db_session.execute(sa.update(Novel).where(Novel.id == novel_id).values(chat_room_id=None))
                await db_session.commit()
                expected_room = None
            revision = await db_session.scalar(
                sa.select(NovelChapterRevision.id).where(NovelChapterRevision.chapter_id == chapter.id)
            )
            resp = await db_client.post(
                f"/novels/{novel_id}/chapters/{chapter.id}/ai-edits",
                json={
                    "baseRevisionId": str(revision),
                    "paragraphStart": 0,
                    "paragraphEnd": 1,
                    "instruction": "고쳐 줘",
                    "expectedCost": 20,
                },
            )

    assert resp.status_code == 202, resp.text
    (usage,) = await _usages(db_session, room.user_id)
    assert usage[:5] == ("novel", novel.content_id, creator.id, expected_room, novel_id)
    assert await _spends_without_usage(db_session, room.user_id) == []


async def test_a_novel_job_on_a_restricted_work_charges_nothing_and_records_nothing(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, enqueued: list[uuid.UUID]
) -> None:
    """원작이 이용제한이면 차감 전에 403 이다 — 원장도 사용처도 남지 않는다."""
    room, novel_id = await _novel_setup(db_client, db_session, monkeypatch)
    novel, _ = await _hand_to_another_creator(db_session, novel_id)
    await db_session.execute(
        sa.update(Content).where(Content.id == novel.content_id).values(moderation_status=ModerationStatus.RESTRICTED)
    )
    await db_session.commit()

    resp = await db_client.post(
        f"/novels/{novel_id}/chapters", json={"endMessageId": str(room.turns[1][1].id), "expectedCost": 40}
    )

    assert resp.status_code == 403, resp.text
    spends = await db_session.scalar(
        sa.select(sa.func.count()).select_from(CloverLedger).where(CloverLedger.user_id == room.user_id)
    )
    assert (spends, await _usages(db_session, room.user_id)) == (0, [])


async def test_a_chain_records_one_usage_on_the_parent_whose_net_use_is_what_its_batches_wrote(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, enqueued: list[uuid.UUID]
) -> None:
    """연쇄는 부모만 차감하고 자식은 0 이라 사용처는 부모 하나다. 묶음 둘(화 수 상한 3씩, 240 선차감) 중 첫 묶음이 한 화,
    둘째가 세 화를 내 네 화(160)를 쓰고 80 을 돌려받는다 — 그 사용처의 배분 순사용이 160 이다."""
    monkeypatch.setattr(settings, "novelize_heartbeat_interval_seconds", 3600)
    monkeypatch.setattr(settings, "novelize_heartbeat_expiry_seconds", 60)
    monkeypatch.setattr(settings, "novelize_chapter_max_turns", 2)
    monkeypatch.setattr(settings, "novelize_episode_target_chars", 1)
    room, novel_id = await _novel_setup(db_client, db_session, monkeypatch, turns=3)
    await clover.grant(db_session, user_id=room.user_id, amount=200, kind="admin_grant")
    await db_session.commit()
    _, creator = await _hand_to_another_creator(db_session, novel_id)
    estimate = (await db_client.get(f"/novels/{novel_id}/chain-estimate")).json()["options"][0]
    assert (estimate["batchCount"], estimate["cost"]) == (2, 240)
    started = await db_client.post(
        f"/novels/{novel_id}/chain", json={"model": "gemini", "expectedCost": 240, "maxBatches": 2}
    )
    assert started.status_code == 202, started.text
    body = "비가 내리는 저녁이었다. 서진은 창가에 섰다.\n\n" + "도윤이 잔을 밀어 주었다. " * 20
    fake = _ChainOutputs([_batch_output(body), _batch_output(body, body, body)])

    await runner.run_chain(
        async_sessionmaker(bind=db_session.bind, expire_on_commit=False, join_transaction_mode="create_savepoint"),
        fake,
        uuid.UUID(started.json()["id"]),
    )

    usages = await db_session.execute(
        sa.select(CloverSpendUsage.spend_ledger_id, CloverSpendUsage.novel_id, CloverSpendUsage.content_owner_user_id)
        .where(CloverSpendUsage.spender_user_id == room.user_id)
    )
    ((ledger_id, usage_novel, owner),) = usages.all()
    assert (usage_novel, owner) == (novel_id, creator.id)
    net = await db_session.scalar(
        sa.select(sa.func.sum(CloverSpendAllocation.amount - CloverSpendAllocation.refunded_amount)).where(
            CloverSpendAllocation.spend_ledger_id == ledger_id
        )
    )
    assert net == 160
    assert await _spends_without_usage(db_session, room.user_id) == []


class _ChainOutputs(LLMClient):
    """연쇄의 묶음 생성 호출마다 `outputs` 를 차례로 흘린다. 경계 제안은 실패시켜 턴 상한 끝에서 끊게 한다."""

    def __init__(self, outputs: list[str]) -> None:
        self.outputs = outputs

    async def generate(
        self,
        prompt: str,
        system_instruction: str | None = None,
        stop_sequences: list[str] | None = None,
        *,
        usage: LLMCallContext,
    ) -> AsyncIterator[str]:
        yield self.outputs.pop(0)

    async def generate_structured(
        self, prompt: str, response_schema: Any, images: Any = None, *, usage: LLMCallContext
    ) -> Any:
        raise AssertionError("소설화는 지시문 없는 구조화 호출을 쓰지 않는다")

    async def generate_structured_with_instruction(
        self, prompt: str, response_schema: type[T], *, system_instruction: str, usage: LLMCallContext
    ) -> T:
        raise LLMClientError("경계 제안 실패")


# ── 구조: 새 차감 경로가 사용처를 빠뜨리지 않는다 ───────────────────────────────
# 사용처가 있어야 하는 차감 종류와, 작품 맥락이 없어 사용처를 남기지 않는 종류. 둘 다에 없는 종류가 `src/` 에 나타나면
# 어느 쪽인지 정할 때까지 이 테스트가 깬다.
_USAGE_REQUIRED_KINDS = {"chat_spend", "novelize_spend", "novel_read_spend"}
_NO_USAGE_KINDS = {"image_spend"}


def _spend_calls() -> Iterator[tuple[str, ast.Call]]:
    for path in sorted(_SRC.rglob("*.py")):
        # 문자열의 잘못된 이스케이프(`\d` 등)에 대한 컴파일 경고는 구문 트리와 무관하다.
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else func.id if isinstance(func, ast.Name) else None
            if name in ("spend", "spend_in_new_transaction"):
                yield f"{path.relative_to(_SRC)}:{node.lineno}", node


def test_every_chat_and_novel_spend_in_src_passes_a_usage() -> None:
    """`src/` 의 `spend`·`spend_in_new_transaction` 호출 중 채팅·소설 차감은 모두 `usage=` 를 넘긴다(`None` 리터럴은 안
    된다). 종류를 변수로 넘기는 호출(차감 래퍼)도 `usage` 를 그대로 넘겨야 한다. 알려진 종류는 모두 실제로 한 번 이상
    나와야 한다 — 목록이 낡아 아무것도 검사하지 않게 되는 것을 막는다."""
    missing: list[str] = []
    unknown: list[str] = []
    seen: set[str] = set()
    for where, call in _spend_calls():
        keywords = {k.arg: k.value for k in call.keywords if k.arg is not None}
        usage = keywords.get("usage")
        has_usage = usage is not None and not (isinstance(usage, ast.Constant) and usage.value is None)
        kind = keywords.get("kind")
        if isinstance(kind, ast.Constant) and isinstance(kind.value, str):
            seen.add(kind.value)
            if kind.value in _USAGE_REQUIRED_KINDS and not has_usage:
                missing.append(where)
            elif kind.value not in _USAGE_REQUIRED_KINDS | _NO_USAGE_KINDS:
                unknown.append(f"{where} {kind.value}")
        elif not has_usage:
            missing.append(where)

    assert missing == []
    assert unknown == []
    assert seen == _USAGE_REQUIRED_KINDS | _NO_USAGE_KINDS
