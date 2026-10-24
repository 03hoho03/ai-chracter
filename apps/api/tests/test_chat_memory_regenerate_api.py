"""방 요약 다시 만들기 — 방 주인이 클로버를 내고 지금 요약을 AI 로 다시 접게 한다.

- 무엇을 다시 접나: 지금 요약(커서가 가장 큰 스냅샷)이 덮는 구간만. 입력은 바로 앞 스냅샷의 요약(첫 접기면 빈 요약)과 두 커서
  사이 원문이다 — 그 구간의 메시지가 바뀌면 되감기가 지금 스냅샷을 지우므로, 스냅샷이 살아 있는 한 구간은 접을 때와 같다.
- 어디에 쓰나: 같은 스냅샷 행을 제자리에서 고친다(커서·장면·사실 행이 그대로 매달려 있다). 고치기 직전 글은 되돌리기 칸에 들어가
  한 번 되돌릴 수 있다 — 사용자가 고친 요약도 다시 만들 수 있고, 그 고친 글이 되돌리기 칸으로 간다.
- 요약 프롬프트는 입력이 같으면 일반 접기와 바이트까지 같다(같은 호출 위치, 같은 조립 함수).
- 값: 방 모델과 무관한 고정 클로버를 먼저 깎고(채팅 상한 예외 계정도 낸다), 어떤 실패로 끝나든 돌려준다. 깎기 전에 거절할 수 있는
  것(스위치 꺼짐·남의 방·가격 불일치·버전 불일치·요약 없음·이미 진행 중)은 깎지 않는다.
- 같은 방에는 한 번에 하나만 — 진행 중에 들어온 두 번째 요청은 기다리지 않고 409 이고 깎지 않는다.
- 그사이 접기·편집·되감기가 기억을 바꿨으면(버전이 달라졌으면) 결과를 버리고 409 로 돌려준다. 반대로 다시 만들기가 먼저 끝나면
  진행 중이던 접기가 결과를 버린다.
- 기억 보기 스위치가 꺼져 있으면 라우트는 등록된 채 404 `MEMORY_ITEMS_DISABLED` 다.

깨지는 시나리오: 새 스냅샷을 만들어 장면·사실이 떨어져 나감, 고친 요약이 되돌릴 수 없이 사라짐, 실패했는데 클로버가 빠진 채 남음,
두 탭에서 눌러 두 번 깎임, 접기와 겹쳐 접힌 대화가 요약에서 빠짐, 다시 만든 요약이 일반 접기와 다른 지시로 만들어짐.
"""

import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

import httpx
import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from api.chat import memory_fold, memory_regenerate
from api.chat.prompt_builder import (
    MemorySummaryResult,
    PromptLane,
    PromptNames,
    PromptRenderError,
    StatRuleJudgmentResult,
    load_active_prompt_set,
)
from api.chat.router import _resolve_starting_setup
from api.chat.turn_prompt import build_room_prompt
from api.core import clover
from api.core.config import settings
from api.db.models import (
    ChatMemoryEpisode,
    ChatMemoryFact,
    ChatRoom,
    ChatRoomMemorySnapshot,
    CloverLedger,
    CloverSpendUsage,
    Content,
    User,
)
from api.db.models.content import ModerationStatus
from api.db.models.persona import UserPersona
from api.llm.client import LLMCallContext, LLMClient, LLMClientError, request_timeout_ms
from factories import (
    Room,
    _clear_llm_override,
    _login_as,
    _make_memory_episode,
    _make_memory_fact,
    _make_user_with_clover_lot,
    _memory_scope_covers_gemini,
    _memory_version,
    _NeverCalledLLMClient,
    _open_room,
    _override_llm_client,
    _room_messages,
)

REGENERATED = "[REGEN] 둘은 서점에서 다시 만났다"
_SPEND = "memory_summary_spend"
_REFUND = "memory_summary_refund"
_SLOT_HEAD = "[비밀 표기]\n- 이 이야기의 인물 이름: "

Outcome = str | Exception | Callable[[], Awaitable[str]]


class RegenerateLLMClient(LLMClient):
    """요약 스키마에 답하고, 스토리 방 보내기의 스탯 판정에는 변화 없음을 준다. `outcomes` 를 차례로 준다(문자열은 요약 본문, 예외는 raise, 콜러블은 먼저 불러 그사이 다른 쓰기를
    흉내 낸다). 다 쓰면 `REGENERATED`. 생성은 고정 응답 — 같은 방에서 보내기로 접기를 일으키는 테스트가 쓴다."""

    def __init__(self, *outcomes: Outcome) -> None:
        self.outcomes = list(outcomes)
        self.summary_prompts: list[str] = []
        self.summary_usages: list[LLMCallContext] = []

    async def generate(
        self,
        prompt: str,
        system_instruction: str | None = None,
        stop_sequences: list[str] | None = None,
        *,
        usage: LLMCallContext,
    ) -> AsyncIterator[str]:
        yield "새 응답"

    async def generate_structured(
        self, prompt: str, response_schema: Any, images: Any = None, *, usage: LLMCallContext
    ) -> Any:
        if response_schema is StatRuleJudgmentResult:
            return StatRuleJudgmentResult(fired_rule_ids=[])
        assert response_schema is MemorySummaryResult, response_schema
        self.summary_prompts.append(prompt)
        self.summary_usages.append(usage)
        outcome = self.outcomes.pop(0) if self.outcomes else REGENERATED
        if isinstance(outcome, Exception):
            raise outcome
        if callable(outcome):
            outcome = await outcome()
        return MemorySummaryResult(summary=outcome)


@pytest.fixture
def items_visible(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "memory_items_visible", True)


def _path(room: Room) -> str:
    return f"/chat-rooms/{room.room_id}/memory/summary/regenerate"


async def _regenerate(
    db_client: httpx.AsyncClient, room: Room, fake: LLMClient, *, version: int = 0, expected_cost: int = 10
) -> httpx.Response:
    _override_llm_client(fake)
    try:
        return await db_client.post(_path(room), json={"version": version, "expectedCost": expected_cost})
    finally:
        _clear_llm_override()


async def _snapshot(db_session: AsyncSession, room: Room, *, turn: int, text: str, **fields: Any) -> uuid.UUID:
    assistant = room.turns[turn][1]
    row = ChatRoomMemorySnapshot(
        chat_room_id=room.room_id,
        cursor_created_at=assistant.created_at,
        cursor_message_id=assistant.id,
        summary_text=text,
        source=fields.pop("source", "auto"),
        **fields,
    )
    db_session.add(row)
    await db_session.commit()
    return row.id


async def _room(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    *,
    turns: int = 25,
    balance: int = 100,
    exempt: bool = False,
    lane: str = "character",
) -> tuple[Room, uuid.UUID]:
    """클로버가 `balance` 인 사용자의 방에 스냅샷 둘(턴 10 "앞 요약", 턴 20 "AI가 접은 요약")을 심고 (방, 지금 스냅샷 id)."""
    user = await _make_user_with_clover_lot(db_session, clover_balance=balance, rate_limit_exempt=exempt)
    room = await _open_room(db_client, db_session, turns=turns, user=user, lane=lane)
    await _snapshot(db_session, room, turn=10, text="앞 요약")
    current = await _snapshot(db_session, room, turn=20, text="AI가 접은 요약")
    return room, current


async def _ledger(db_session: AsyncSession, user_id: uuid.UUID) -> list[tuple[str, int]]:
    rows = await db_session.execute(
        sa.select(CloverLedger.kind, CloverLedger.amount)
        .where(CloverLedger.user_id == user_id)
        .order_by(CloverLedger.created_at, CloverLedger.amount)
    )
    return [(kind, amount) for kind, amount in rows.all()]


async def _usage_count(db_session: AsyncSession, user_id: uuid.UUID) -> int:
    """그 사용자의 원장 행에 매달린 사용처 행 수. 요약 다시 만들기는 정산에서 빠지므로 차감·환불 어느 쪽에도 0 이어야 한다."""
    count: int | None = await db_session.scalar(
        sa.select(sa.func.count())
        .select_from(CloverSpendUsage)
        .join(CloverLedger, CloverLedger.id == CloverSpendUsage.spend_ledger_id)
        .where(CloverLedger.user_id == user_id)
    )
    return count or 0


async def _balance(db_session: AsyncSession, user_id: uuid.UUID) -> int | None:
    balance: int | None = await db_session.scalar(sa.select(User.clover_balance).where(User.id == user_id))
    return balance


async def _row(db_session: AsyncSession, snapshot_id: uuid.UUID) -> sa.Row[Any] | None:
    return (
        await db_session.execute(
            sa.select(
                ChatRoomMemorySnapshot.id,
                ChatRoomMemorySnapshot.cursor_message_id,
                ChatRoomMemorySnapshot.summary_text,
                ChatRoomMemorySnapshot.previous_text,
                ChatRoomMemorySnapshot.previous_source,
                ChatRoomMemorySnapshot.source,
            ).where(ChatRoomMemorySnapshot.id == snapshot_id)
        )
    ).first()


async def _snapshot_ids(db_session: AsyncSession, room: Room) -> list[uuid.UUID]:
    rows = await db_session.scalars(
        sa.select(ChatRoomMemorySnapshot.id)
        .where(ChatRoomMemorySnapshot.chat_room_id == room.room_id)
        .order_by(ChatRoomMemorySnapshot.cursor_created_at)
    )
    return list(rows.all())


# --- 스위치 ---------------------------------------------------------------------------------


async def test_route_is_off_while_the_items_switch_is_off(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    room, current = await _room(db_client, db_session)

    resp = await _regenerate(db_client, room, _NeverCalledLLMClient())

    assert resp.status_code == 404
    assert resp.json()["detail"] == {"code": "MEMORY_ITEMS_DISABLED"}
    assert await _ledger(db_session, room.user_id) == []
    row = await _row(db_session, current)
    assert row is not None and row.summary_text == "AI가 접은 요약"


# --- 제자리에서 다시 접기 ---------------------------------------------------------------------


@pytest.mark.usefixtures("items_visible")
async def test_regenerate_refolds_the_previous_summary_and_the_folded_turns_in_place(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    room, current = await _room(db_client, db_session)
    episode = _make_memory_episode(room.room_id, current)
    fact = _make_memory_fact(room.room_id, current)
    db_session.add_all([episode, fact])
    await db_session.commit()
    fake = RegenerateLLMClient()

    resp = await _regenerate(db_client, room, fake)

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["summary"]["text"] == REGENERATED
    assert body["summary"]["source"] == "auto"
    assert body["summary"]["canRevert"] is True
    assert body["version"] == 1
    (prompt,) = fake.summary_prompts
    assert "앞 요약" in prompt and "AI가 접은 요약" not in prompt
    assert "[U11]" in prompt and "[A20]" in prompt
    assert "[A10]" not in prompt and "[U21]" not in prompt
    assert [usage.call_site for usage in fake.summary_usages] == ["chat_memory_summary"]
    # 새 행이 아니라 같은 행 — 커서와 거기 매달린 장면·사실이 그대로다.
    assert len(await _snapshot_ids(db_session, room)) == 2
    row = await _row(db_session, current)
    assert row is not None
    assert row.cursor_message_id == room.turns[20][1].id
    assert (row.summary_text, row.previous_text, row.previous_source, row.source) == (
        REGENERATED,
        "AI가 접은 요약",
        "auto",
        "auto",
    )
    assert await db_session.scalar(sa.select(ChatMemoryEpisode.snapshot_id).where(ChatMemoryEpisode.id == episode.id)) == current
    assert await db_session.scalar(sa.select(ChatMemoryFact.snapshot_id).where(ChatMemoryFact.id == fact.id)) == current
    assert await _memory_version(db_session, room) == 1
    assert await _ledger(db_session, room.user_id) == [(_SPEND, -10)]
    assert await _balance(db_session, room.user_id) == 90
    assert await _usage_count(db_session, room.user_id) == 0


@pytest.mark.usefixtures("items_visible")
async def test_first_summary_is_refolded_from_an_empty_previous_summary(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = await _make_user_with_clover_lot(db_session, clover_balance=100)
    room = await _open_room(db_client, db_session, turns=15, user=user)
    current = await _snapshot(db_session, room, turn=10, text="첫 요약")
    fake = RegenerateLLMClient()

    resp = await _regenerate(db_client, room, fake)

    assert resp.status_code == 200, resp.text
    (prompt,) = fake.summary_prompts
    assert "[U01]" in prompt and "[A10]" in prompt and "[U11]" not in prompt
    assert "첫 요약" not in prompt
    row = await _row(db_session, current)
    assert row is not None and (row.summary_text, row.previous_text) == (REGENERATED, "첫 요약")


@pytest.mark.usefixtures("items_visible")
async def test_user_edited_summary_can_be_regenerated_and_one_revert_brings_the_edit_back(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = await _make_user_with_clover_lot(db_session, clover_balance=100)
    room = await _open_room(db_client, db_session, turns=20, user=user)
    await _snapshot(db_session, room, turn=10, text="앞 요약")
    current = await _snapshot(
        db_session,
        room,
        turn=20,
        text="사용자가 고친 요약",
        source="user",
        previous_text="AI가 접은 요약",
        previous_source="auto",
    )

    regenerated = await _regenerate(db_client, room, RegenerateLLMClient())
    reverted = await db_client.post(f"/chat-rooms/{room.room_id}/memory/summary/revert", json={"version": 1})

    assert regenerated.status_code == 200, regenerated.text
    assert reverted.status_code == 200, reverted.text
    assert reverted.json()["summary"]["text"] == "사용자가 고친 요약"
    assert reverted.json()["summary"]["source"] == "user"
    assert reverted.json()["summary"]["canRevert"] is False
    row = await _row(db_session, current)
    assert row is not None
    assert (row.summary_text, row.previous_text, row.source) == ("사용자가 고친 요약", None, "user")


# --- 깎기 전에 거절 -------------------------------------------------------------------------


@pytest.mark.usefixtures("items_visible")
async def test_stale_version_is_rejected_before_charging(db_client: httpx.AsyncClient, db_session: AsyncSession) -> None:
    room, current = await _room(db_client, db_session)
    await db_session.execute(sa.update(ChatRoom).where(ChatRoom.id == room.room_id).values(memory_version=3))
    await db_session.commit()

    resp = await _regenerate(db_client, room, _NeverCalledLLMClient(), version=2)

    assert resp.status_code == 409
    assert resp.json()["detail"] == {"code": "MEMORY_VERSION_CONFLICT"}
    assert await _ledger(db_session, room.user_id) == []
    assert await _memory_version(db_session, room) == 3
    row = await _row(db_session, current)
    assert row is not None and row.summary_text == "AI가 접은 요약"


@pytest.mark.usefixtures("items_visible")
async def test_room_without_a_summary_is_rejected_before_charging(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = await _make_user_with_clover_lot(db_session, clover_balance=100)
    room = await _open_room(db_client, db_session, turns=5, user=user)

    resp = await _regenerate(db_client, room, _NeverCalledLLMClient())

    assert resp.status_code == 409
    assert resp.json()["detail"] == {"code": "MEMORY_SUMMARY_NOT_READY"}
    assert await _ledger(db_session, room.user_id) == []


@pytest.mark.usefixtures("items_visible")
async def test_price_other_than_the_one_on_the_confirm_dialog_is_rejected_before_charging(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    room, _current = await _room(db_client, db_session)

    resp = await _regenerate(db_client, room, _NeverCalledLLMClient(), expected_cost=9)

    assert resp.status_code == 409
    assert resp.json()["detail"] == {"code": "MEMORY_SUMMARY_REGENERATE_PRICE_CHANGED", "currentCost": 10}
    assert await _ledger(db_session, room.user_id) == []


@pytest.mark.usefixtures("items_visible")
async def test_price_is_read_from_its_own_constant_at_request_time(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """가격은 방 모델의 턴 가격에서 끌어오지 않는 별도 상수다 — 턴 가격을 바꿔도 따라가지 않고, 이 상수를 바꾸면 따라간다."""
    monkeypatch.setattr(clover, "CHAT_TURN_COST", 999)
    monkeypatch.setattr(clover, "MEMORY_SUMMARY_REGENERATE_COST", 7)
    room, _current = await _room(db_client, db_session)

    resp = await _regenerate(db_client, room, RegenerateLLMClient(), expected_cost=7)

    assert resp.status_code == 200, resp.text
    assert await _ledger(db_session, room.user_id) == [(_SPEND, -7)]


@pytest.mark.usefixtures("items_visible")
async def test_someone_elses_room_is_refused_before_charging(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    room, _current = await _room(db_client, db_session)
    stranger = await _make_user_with_clover_lot(db_session, clover_balance=100)
    await db_session.commit()
    await _login_as(db_client, stranger.id)

    resp = await _regenerate(db_client, room, _NeverCalledLLMClient())

    assert resp.status_code == 403
    assert await _ledger(db_session, stranger.id) == []
    assert await _ledger(db_session, room.user_id) == []


@pytest.mark.usefixtures("items_visible")
async def test_restricted_work_does_not_call_the_model_or_charge(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    room, _current = await _room(db_client, db_session)
    content_id = await db_session.scalar(sa.select(ChatRoom.content_id).where(ChatRoom.id == room.room_id))
    await db_session.execute(
        sa.update(Content).where(Content.id == content_id).values(moderation_status=ModerationStatus.RESTRICTED)
    )
    await db_session.commit()

    resp = await _regenerate(db_client, room, _NeverCalledLLMClient())

    assert resp.status_code == 403
    assert resp.json()["detail"] == {"code": "CONTENT_RESTRICTED"}
    assert await _ledger(db_session, room.user_id) == []


# --- 값 ---------------------------------------------------------------------------------


@pytest.mark.usefixtures("items_visible")
async def test_short_balance_gets_the_clover_required_contract_without_calling_the_model(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    room, current = await _room(db_client, db_session, balance=9)

    resp = await _regenerate(db_client, room, _NeverCalledLLMClient())

    assert resp.status_code == 429
    detail = resp.json()["detail"]
    assert detail["code"] == "CLOVER_REQUIRED"
    assert detail["window"] == "memory_summary"
    assert isinstance(detail["retryAfterSeconds"], int)
    assert await _ledger(db_session, room.user_id) == []
    row = await _row(db_session, current)
    assert row is not None and row.summary_text == "AI가 접은 요약"


@pytest.mark.usefixtures("items_visible")
@pytest.mark.parametrize(("balance", "status"), [pytest.param(100, 200, id="charged"), pytest.param(0, 429, id="short")])
async def test_rate_limit_exempt_account_pays_too(
    db_client: httpx.AsyncClient, db_session: AsyncSession, balance: int, status: int
) -> None:
    """채팅 상한 예외 계정도 클로버를 낸다 — 하루 무료 대화도 쓰지 않으므로 잔액이 없으면 거절이다."""
    room, _current = await _room(db_client, db_session, balance=balance, exempt=True)

    resp = await _regenerate(db_client, room, RegenerateLLMClient())

    assert resp.status_code == status, resp.text
    assert await _ledger(db_session, room.user_id) == ([(_SPEND, -10)] if status == 200 else [])


@pytest.mark.usefixtures("items_visible")
@pytest.mark.parametrize(
    "outcome",
    [
        pytest.param(LLMClientError("boom"), id="llm-error"),
        pytest.param("   ", id="blank-summary"),
        pytest.param(PromptRenderError("렌더 실패"), id="render-error"),
    ],
)
async def test_failed_call_refunds_and_leaves_the_summary_alone(
    db_client: httpx.AsyncClient, db_session: AsyncSession, outcome: Exception | str
) -> None:
    room, current = await _room(db_client, db_session)

    resp = await _regenerate(db_client, room, RegenerateLLMClient(outcome))

    assert resp.status_code == 503
    assert resp.json()["detail"] == {"code": "MEMORY_SUMMARY_REGENERATE_UNAVAILABLE"}
    assert await _ledger(db_session, room.user_id) == [(_SPEND, -10), (_REFUND, 10)]
    assert await _balance(db_session, room.user_id) == 100
    assert await _usage_count(db_session, room.user_id) == 0
    row = await _row(db_session, current)
    assert row is not None and (row.summary_text, row.previous_text) == ("AI가 접은 요약", None)
    assert await _memory_version(db_session, room) == 0


@pytest.mark.usefixtures("items_visible")
async def test_ledger_history_lists_the_spend_as_use_and_the_refund_as_earn(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    room, _current = await _room(db_client, db_session)
    await _regenerate(db_client, room, RegenerateLLMClient(LLMClientError("boom")))

    use = await db_client.get("/me/clover/ledger", params={"category": "use"})
    earn = await db_client.get("/me/clover/ledger", params={"category": "earn"})

    assert use.status_code == 200 and earn.status_code == 200
    assert [(item["kind"], item["amount"], item["category"]) for item in use.json()["items"]] == [(_SPEND, -10, "use")]
    assert (_REFUND, 10, "earn") in [(item["kind"], item["amount"], item["category"]) for item in earn.json()["items"]]


# --- 겹침 ------------------------------------------------------------------------------


@pytest.mark.usefixtures("items_visible")
async def test_second_request_while_one_is_in_flight_is_rejected_without_charging(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    room, current = await _room(db_client, db_session)
    nested: list[httpx.Response] = []

    async def _press_again_while_waiting() -> str:
        nested.append(await db_client.post(_path(room), json={"version": 0, "expectedCost": 10}))
        return REGENERATED

    first = await _regenerate(db_client, room, RegenerateLLMClient(_press_again_while_waiting))
    after = await _regenerate(db_client, room, RegenerateLLMClient(), version=1)

    assert first.status_code == 200, first.text
    (second,) = nested
    assert second.status_code == 409
    assert second.json()["detail"] == {"code": "MEMORY_SUMMARY_REGENERATE_IN_PROGRESS"}
    # 끝난 뒤에는 다시 받는다(진행 표시가 풀렸다).
    assert after.status_code == 200, after.text
    assert await _ledger(db_session, room.user_id) == [(_SPEND, -10), (_SPEND, -10)]
    row = await _row(db_session, current)
    assert row is not None and row.previous_text == REGENERATED


def test_in_progress_marker_outlives_the_summary_call_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    """진행 표시가 요약 호출보다 먼저 풀리면 그사이 들어온 두 번째 요청이 깎인다. 표시의 수명은 요약 호출이 요청에 싣는
    시간 상한보다 길고, 그 상한 설정을 바꾸면 따라간다."""
    assert memory_regenerate.regenerate_lock_ttl_ms() > request_timeout_ms(memory_fold.SUMMARY_CALL_SITE)
    monkeypatch.setattr(settings, "gemini_memory_summary_timeout_ms", 180_000)
    assert memory_regenerate.regenerate_lock_ttl_ms() > 180_000


async def test_in_progress_marker_is_taken_with_the_derived_lifetime(monkeypatch: pytest.MonkeyPatch) -> None:
    taken: list[int] = []

    async def _acquire(_client: Any, _key: str, *, ttl_ms: int) -> str:
        taken.append(ttl_ms)
        return "token"

    async def _release(_client: Any, _key: str, _token: str) -> bool:
        return True

    monkeypatch.setattr(memory_regenerate, "try_acquire_lock", _acquire)
    monkeypatch.setattr(memory_regenerate, "release_lock", _release)
    async with memory_regenerate.hold_regenerate_lock(uuid.uuid4()):
        pass

    assert taken == [memory_regenerate.regenerate_lock_ttl_ms()]


@pytest.mark.usefixtures("items_visible")
async def test_fold_that_commits_during_the_call_wins_and_the_charge_is_refunded(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """요약을 기다리는 사이 접기가 새 스냅샷을 커밋했다(버전을 올리고 행을 넣는다). 다시 만든 글을 옛 스냅샷에 쓰면 사용자가
    고른 시점과 다른 요약을 바꾸게 되므로 버리고 409 로 돌려준다."""
    room, current = await _room(db_client, db_session)

    async def _a_fold_commits() -> str:
        await db_session.execute(
            sa.update(ChatRoom).where(ChatRoom.id == room.room_id).values(memory_version=ChatRoom.memory_version + 1)
        )
        await _snapshot(db_session, room, turn=25, text="새로 접힌 요약")
        return REGENERATED

    resp = await _regenerate(db_client, room, RegenerateLLMClient(_a_fold_commits))

    assert resp.status_code == 409
    assert resp.json()["detail"] == {"code": "MEMORY_VERSION_CONFLICT"}
    assert await _ledger(db_session, room.user_id) == [(_SPEND, -10), (_REFUND, 10)]
    row = await _row(db_session, current)
    assert row is not None and (row.summary_text, row.previous_text) == ("AI가 접은 요약", None)
    assert len(await _snapshot_ids(db_session, room)) == 3
    assert await _memory_version(db_session, room) == 1


@pytest.mark.usefixtures("items_visible")
async def test_fold_in_progress_discards_its_result_when_a_regenerate_commits_first(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """접기가 버전을 읽고 요약을 기다리는 사이 다시 만들기가 같은 버전으로 커밋했다. 접기는 버전이 달라진 것을 보고 결과를
    버린다 — 다시 만든 요약 위에 옛 요약을 입력으로 쓴 새 스냅샷이 얹히지 않는다."""
    room, current = await _room(db_client, db_session, turns=50)
    regenerate_responses: list[httpx.Response] = []

    async def _regenerate_meanwhile() -> str:
        regenerate_responses.append(await _regenerate(db_client, room, RegenerateLLMClient()))
        return "[FOLD] 접기가 만든 요약"

    prompt_set, sections = await load_active_prompt_set(db_session, lane="character")
    await memory_fold.fold_memory(
        async_sessionmaker(bind=db_session.bind, expire_on_commit=False),
        RegenerateLLMClient(_regenerate_meanwhile),
        room_id=room.room_id,
        user_id=room.user_id,
        prompt_set=prompt_set,
        sections=sections,
        is_story_chat=False,
        names=PromptNames(persona_name=None, char_name="캐릭터"),
        writing_model="gemini",
    )

    (regenerated,) = regenerate_responses
    assert regenerated.status_code == 200, regenerated.text
    assert len(await _snapshot_ids(db_session, room)) == 2
    row = await _row(db_session, current)
    assert row is not None and row.summary_text == REGENERATED
    assert await _memory_version(db_session, room) == 1


# --- 일반 접기와 같은 프롬프트 ------------------------------------------------------------------


async def _persona_room(
    db_client: httpx.AsyncClient, db_session: AsyncSession, *, turns: int, lane: str
) -> Room:
    user = await _make_user_with_clover_lot(db_session, clover_balance=100)
    room = await _open_room(db_client, db_session, turns=turns, user=user, lane=lane)
    persona = UserPersona(user_id=user.id, name="하늘이")
    db_session.add(persona)
    await db_session.flush()
    await db_session.execute(sa.update(ChatRoom).where(ChatRoom.id == room.room_id).values(persona_id=persona.id))
    await db_session.commit()
    return room


@pytest.mark.usefixtures("items_visible")
@pytest.mark.parametrize("secret_marking", [pytest.param(False, id="marking-off"), pytest.param(True, id="marking-on")])
@pytest.mark.parametrize(
    ("lane", "turns", "earlier"),
    [
        pytest.param("character", 29, False, id="character-first-fold"),
        pytest.param("story", 39, True, id="story-second-fold"),
    ],
)
async def test_summary_prompt_is_byte_identical_to_the_fold_that_made_it(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    secret_marking: bool,
    lane: str,
    turns: int,
    earlier: bool,
) -> None:
    """보내기가 일으킨 일반 접기(이름은 그 턴의 생성 프롬프트에서 옴)와, 바로 뒤 같은 스냅샷을 다시 만드는 요청(이름은 방 프로필로
    다시 만듦)의 요약 프롬프트가 같다. 비밀 표기가 켜진 쪽은 슬롯이 실제로 실린 채 비교한다."""
    monkeypatch.setattr(settings, "memory_summary_secret_marking", secret_marking)
    _memory_scope_covers_gemini(monkeypatch)
    room = await _persona_room(db_client, db_session, turns=turns, lane=lane)
    if earlier:
        await _snapshot(db_session, room, turn=10, text="[PREV] 앞선 요약")
    fake = RegenerateLLMClient("[FOLD] 접기가 만든 요약")
    _override_llm_client(fake)
    try:
        sent = await db_client.post(f"/chat-rooms/{room.room_id}/messages", json={"content": "새 메시지"})
    finally:
        _clear_llm_override()
    assert sent.status_code == 200, sent.text
    assert len(fake.summary_prompts) == 1

    resp = await _regenerate(db_client, room, fake, version=1)

    assert resp.status_code == 200, resp.text
    folded, regenerated = fake.summary_prompts
    assert regenerated == folded
    assert ("[PREV] 앞선 요약" in folded) is earlier
    assert (_SLOT_HEAD in folded) is secret_marking


# --- 이름 헬퍼 -------------------------------------------------------------------------


@pytest.mark.parametrize("lane", ["character", "story"])
@pytest.mark.parametrize("with_persona", [pytest.param(True, id="persona"), pytest.param(False, id="no-persona")])
async def test_room_names_outside_a_turn_match_the_names_a_turn_uses(
    db_client: httpx.AsyncClient, db_session: AsyncSession, lane: PromptLane, with_persona: bool
) -> None:
    if with_persona:
        room = await _persona_room(db_client, db_session, turns=1, lane=lane)
    else:
        room = await _open_room(db_client, db_session, turns=1, lane=lane)
    chat_room = await db_session.get(ChatRoom, room.room_id)
    assert chat_room is not None
    setup = await _resolve_starting_setup(db_session, chat_room)
    prompt_set, sections = await load_active_prompt_set(db_session, lane=lane)
    history = await _room_messages(db_session, room.room_id)
    turn = await build_room_prompt(db_session, chat_room, setup, history, "안녕", None, prompt_set, sections)

    # 헬퍼가 생기기 전에도 이 파일의 다른 테스트가 각자의 이유로 실패하도록 여기서 가져온다.
    from api.chat.turn_prompt import room_prompt_names

    names = await room_prompt_names(db_session, chat_room, is_story_chat=setup is not None)

    assert names == turn.names
    assert (names.persona_name == "하늘이") is with_persona


# --- 다음 턴 생성 프롬프트 ----------------------------------------------------------------------


@pytest.mark.usefixtures("items_visible")
async def test_next_turn_generation_prompt_changes_only_in_the_summary_text(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    room, _current = await _room(db_client, db_session)
    chat_room = await db_session.get(ChatRoom, room.room_id)
    assert chat_room is not None
    prompt_set, sections = await load_active_prompt_set(db_session, lane="character")

    async def _prompt() -> str:
        history = await _room_messages(db_session, room.room_id)
        return (await build_room_prompt(db_session, chat_room, None, history, "안녕", None, prompt_set, sections)).prompt

    before = await _prompt()
    resp = await _regenerate(db_client, room, RegenerateLLMClient())
    after = await _prompt()

    assert resp.status_code == 200, resp.text
    assert "AI가 접은 요약" in before
    assert after != before
    assert after == before.replace("AI가 접은 요약", REGENERATED)

