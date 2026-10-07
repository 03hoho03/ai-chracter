"""남은 대화 한 번에(연쇄 생성) — 모델별 견적, 부모 차감, 묶음마다 자식 하나씩, 쓴 몫·남은 몫 환불, 실패·만료·시간 상한.

라우트 시험은 부모를 띄우는 함수(`enqueue_chain_job`)를 기록용으로 바꿔 끼우고, 실행은 그 id 로 `run_chain` 을 직접
기다린다(`test_novelize_runner.py` 와 같은 세션 팩토리 — 테스트 커넥션 하나에 SAVEPOINT 로 붙는다). 그래서 heartbeat 주기를
크게 늘려 두고, 만료는 `heartbeat_at` 을 과거로 옮겨 만든다(테스트 안 `now()` 는 트랜잭션 시작 시각으로 고정이다).

방의 메시지는 짧아(20자) 화 수 계산은 늘 1화다. 화 수 상한까지 받는 갈래는 화 목표 길이를 1자로 줄여 만든다."""

import asyncio
import contextlib
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from datetime import timedelta
from typing import Any

import httpx
import pytest
import sqlalchemy as sa
from factories import (
    Room,
    _add_chapter,
    _allow_novel_premium,
    _batch_output,
    _clear_llm_override,
    _novel_ledger,
    _novel_setup,
    _override_llm_client,
    _room_messages,
)
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from api.core import clover
from api.core.config import settings
from api.db.models import Novel, NovelBatch, NovelChapter, NovelJob, User
from api.db.models.clover import CloverLot
from api.llm.client import LLMCallContext, LLMClient, LLMClientError, T
from api.novelize import router as novelize_router
from api.novelize import runner
from api.novelize.prompts import NovelizeBoundaryResult

_BODY = "비가 내리는 저녁이었다. 서진은 가방을 내려놓고 창가에 섰다.\n\n" + "도윤이 잔을 밀어 주었다. " * 20


class _ChainLLM(LLMClient):
    """연쇄 페이크. 묶음 생성 `n` 번째 호출(0부터)은 `outputs[n]`(없으면 한 화)을 흘리고, `errors[n]` 이 있으면 그것을
    낸다. `during[n]` 은 그 호출 순간 실행할 일(그 사이 다른 경로가 끼어드는 상황)이다. 경계 제안은 `end_turns` 를
    차례로 돌려주고, 값이 None 이거나 떨어지면 호출 실패다."""

    def __init__(
        self,
        outputs: list[str] | None = None,
        *,
        errors: dict[int, Exception] | None = None,
        during: dict[int, Callable[[], Awaitable[None]]] | None = None,
        end_turns: list[int | None] | None = None,
    ) -> None:
        self.outputs = outputs or []
        self.errors = errors or {}
        self.during = during or {}
        self.end_turns = list(end_turns or [])
        self.generate_calls: list[LLMCallContext] = []
        self.boundary_calls: list[str] = []

    async def generate(
        self,
        prompt: str,
        system_instruction: str | None = None,
        stop_sequences: list[str] | None = None,
        *,
        usage: LLMCallContext,
    ) -> AsyncIterator[str]:
        n = len(self.generate_calls)
        self.generate_calls.append(usage)
        if n in self.during:
            await self.during[n]()
        if n in self.errors:
            raise self.errors[n]
        yield self.outputs[n] if n < len(self.outputs) else _batch_output(_BODY)

    async def generate_structured(
        self, prompt: str, response_schema: Any, images: Any = None, *, usage: LLMCallContext
    ) -> Any:
        raise AssertionError("소설화는 지시문 없는 구조화 호출을 쓰지 않는다")

    async def generate_structured_with_instruction(
        self, prompt: str, response_schema: type[T], *, system_instruction: str, usage: LLMCallContext
    ) -> T:
        assert response_schema is NovelizeBoundaryResult
        assert usage.call_site == "novelize_boundary"
        self.boundary_calls.append(prompt)
        end_turn = self.end_turns.pop(0) if self.end_turns else None
        if end_turn is None:
            raise LLMClientError("경계 제안 실패")
        return response_schema.model_validate({"end_turn": end_turn, "reason": "장면이 매듭지어진다"})


@pytest.fixture(autouse=True)
def _slow_heartbeat(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "novelize_heartbeat_interval_seconds", 3600)
    monkeypatch.setattr(settings, "novelize_heartbeat_expiry_seconds", 60)


@pytest.fixture
def enqueued(monkeypatch: pytest.MonkeyPatch) -> list[uuid.UUID]:
    """연쇄 부모를 띄우는 함수를 기록으로 바꾼다. 묶음 하나짜리 작업을 띄우는 함수가 불리면 실패다."""
    seen: list[uuid.UUID] = []

    async def record(_factory: Any, _llm: Any, job_id: uuid.UUID) -> None:
        seen.append(job_id)

    async def wrong(_factory: Any, _llm: Any, job_id: uuid.UUID) -> None:
        raise AssertionError("연쇄 부모를 묶음 작업으로 띄웠다")

    monkeypatch.setattr(novelize_router, "enqueue_chain_job", record)
    monkeypatch.setattr(novelize_router, "enqueue_job", wrong)
    return seen


@pytest.fixture
def llm() -> Iterator[_ChainLLM]:
    fake = _ChainLLM()
    _override_llm_client(fake)
    yield fake
    _clear_llm_override()


def _factory(db_session: AsyncSession) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(bind=db_session.bind, expire_on_commit=False, join_transaction_mode="create_savepoint")


async def _chain_novel(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    *,
    turns: int,
    premium: bool = False,
) -> tuple[Room, uuid.UUID, uuid.UUID]:
    """소설화를 허용한 `turns` 턴 방(오프닝까지 `turns + 1` 턴)의 소설. 잔액은 2,100 클로버이고 `premium` 이면 소설 상위
    모델도 허용한다."""
    room, novel_id = await _novel_setup(db_client, db_session, monkeypatch, turns=turns)
    owner_id = (await db_session.get_one(Novel, novel_id)).user_id
    await clover.grant(db_session, user_id=owner_id, amount=2000, kind="admin_grant")
    await db_session.commit()
    if premium:
        await _allow_novel_premium(db_session, monkeypatch, owner_id)
    return room, novel_id, owner_id


async def _estimate(db_client: httpx.AsyncClient, novel_id: uuid.UUID) -> dict[str, dict[str, Any]]:
    resp = await db_client.get(f"/novels/{novel_id}/chain-estimate")
    assert resp.status_code == 200, resp.text
    return {option["model"]: option for option in resp.json()["options"]}


async def _start(
    db_client: httpx.AsyncClient, novel_id: uuid.UUID, model: str = "gemini", *, max_batches: int | None = None
) -> uuid.UUID:
    """견적에서 고른 모델의 금액·묶음 수로 연쇄를 만들고 부모 id 를 돌려준다. `max_batches` 를 주면 묶음 수를 그만큼
    줄이고 금액도 그 비율대로 낸다."""
    option = (await _estimate(db_client, novel_id))[model]
    batches = option["batchCount"] if max_batches is None else max_batches
    cost = option["cost"] // option["batchCount"] * batches
    resp = await db_client.post(
        f"/novels/{novel_id}/chain", json={"model": model, "expectedCost": cost, "maxBatches": batches}
    )
    assert resp.status_code == 202, resp.text
    return uuid.UUID(resp.json()["id"])


async def _job(db: AsyncSession, job_id: uuid.UUID) -> NovelJob:
    return await db.get_one(NovelJob, job_id, populate_existing=True)


async def _children(db: AsyncSession, parent_id: uuid.UUID) -> list[NovelJob]:
    rows = await db.scalars(
        sa.select(NovelJob)
        .where(NovelJob.parent_job_id == parent_id)
        .order_by(NovelJob.start_message_created_at)
        .execution_options(populate_existing=True)
    )
    return list(rows.all())


async def _batches(db: AsyncSession, novel_id: uuid.UUID) -> list[NovelBatch]:
    rows = await db.scalars(
        sa.select(NovelBatch)
        .where(NovelBatch.novel_id == novel_id)
        .order_by(NovelBatch.ordinal)
        .execution_options(populate_existing=True)
    )
    return list(rows.all())


async def _chapter_count(db: AsyncSession, novel_id: uuid.UUID) -> int:
    return int(
        await db.scalar(sa.select(sa.func.count()).select_from(NovelChapter).where(NovelChapter.novel_id == novel_id))
        or 0
    )


async def _assert_lots_match_balance(db: AsyncSession, user_id: uuid.UUID) -> None:
    balance = await db.scalar(sa.select(User.clover_balance).where(User.id == user_id))
    lots = await db.scalar(
        sa.select(sa.func.coalesce(sa.func.sum(CloverLot.remaining), 0)).where(CloverLot.user_id == user_id)
    )
    assert balance == lots


async def _age_heartbeat(db: AsyncSession, job_id: uuid.UUID) -> None:
    await db.execute(
        sa.update(NovelJob).where(NovelJob.id == job_id).values(heartbeat_at=sa.func.now() - timedelta(hours=1))
    )


# ── 견적 ────────────────────────────────────────────────────────────────────
async def test_estimate_lists_each_allowed_model_with_batches_times_its_episode_cap_and_price(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """같은 남은 대화(5턴)라도 턴 상한이 모델마다 달라 묶음 수가 다르다. 금액은 묶음 수 × 그 모델의 화 수 상한 × 화
    단가다. 한 번의 묶음 수 상한에 닿으면 그 수에서 자른다."""
    _, novel_id, _ = await _chain_novel(db_client, db_session, monkeypatch, turns=4, premium=True)
    monkeypatch.setattr(settings, "novelize_chapter_max_turns", 2)
    monkeypatch.setattr(settings, "novelize_chapter_max_turns_opus", 3)
    monkeypatch.setattr(settings, "novelize_k_max_opus", 2)

    options = await _estimate(db_client, novel_id)

    assert list(options) == ["gemini", "sonnet", "opus"]
    assert [(o["batchCount"], o["maxEpisodeCount"], o["cost"]) for o in options.values()] == [
        (3, 9, 3 * 3 * 40),
        (1, 1, 1 * 1 * 105),
        (2, 4, 2 * 2 * 170),
    ]

    monkeypatch.setattr(settings, "novelize_chain_max_batches", 2)
    capped = await _estimate(db_client, novel_id)
    assert (capped["gemini"]["batchCount"], capped["gemini"]["cost"]) == (2, 2 * 3 * 40)


async def test_estimate_without_premium_access_offers_only_the_default_model(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, novel_id, _ = await _chain_novel(db_client, db_session, monkeypatch, turns=2)

    assert list(await _estimate(db_client, novel_id)) == ["gemini"]


async def test_estimate_and_create_answer_nothing_new_when_every_turn_is_already_a_chapter(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    room, novel_id, owner_id = await _chain_novel(db_client, db_session, monkeypatch, turns=2)
    messages = await _room_messages(db_session, room.room_id)
    await _add_chapter(db_session, novel_id, room, messages[0], messages[-1])

    estimate = await db_client.get(f"/novels/{novel_id}/chain-estimate")
    created = await db_client.post(
        f"/novels/{novel_id}/chain", json={"model": "gemini", "expectedCost": 120, "maxBatches": 1}
    )

    assert (estimate.status_code, estimate.json()["detail"]["code"]) == (409, "NOVEL_NOTHING_NEW")
    assert (created.status_code, created.json()["detail"]["code"]) == (409, "NOVEL_NOTHING_NEW")
    assert await _novel_ledger(db_session, owner_id) == []


# ── 생성 라우트 ─────────────────────────────────────────────────────────────
async def test_create_charges_the_parent_and_pins_its_plan_on_the_row(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    enqueued: list[uuid.UUID],
) -> None:
    """`maxBatches` 는 상한이다 — 남은 대화가 묶음 셋이어도 하나만 고르면 하나 몫만 낸다. 부모 행에는 그 묶음 수와 차감
    때의 화 수 상한·화 단가가 남고, 띄우는 것은 연쇄 실행이다."""
    _, novel_id, owner_id = await _chain_novel(db_client, db_session, monkeypatch, turns=4)
    monkeypatch.setattr(settings, "novelize_chapter_max_turns", 2)

    parent_id = await _start(db_client, novel_id, max_batches=1)

    parent = await _job(db_session, parent_id)
    assert (parent.kind, parent.status, parent.model, parent.charged_amount) == ("chain_generate", "queued", "gemini", 120)
    assert (parent.planned_batches, parent.batch_k_max, parent.unit_price, parent.consumed_amount) == (1, 3, 40, 0)
    assert enqueued == [parent_id]
    assert await _novel_ledger(db_session, owner_id) == [("novelize_spend", -120)]


async def test_create_rejects_a_stale_price_with_the_current_cost_and_charges_nothing(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    enqueued: list[uuid.UUID],
) -> None:
    _, novel_id, owner_id = await _chain_novel(db_client, db_session, monkeypatch, turns=4)
    monkeypatch.setattr(settings, "novelize_chapter_max_turns", 2)

    resp = await db_client.post(
        f"/novels/{novel_id}/chain", json={"model": "gemini", "expectedCost": 120, "maxBatches": 2}
    )

    assert resp.status_code == 409
    assert resp.json()["detail"] == {"code": "NOVELIZE_PRICE_CHANGED", "currentCost": 2 * 3 * 40}
    assert enqueued == []
    assert await _novel_ledger(db_session, owner_id) == []


async def test_create_with_a_premium_model_without_access_is_403_and_writes_no_ledger(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    enqueued: list[uuid.UUID],
) -> None:
    _, novel_id, owner_id = await _chain_novel(db_client, db_session, monkeypatch, turns=2)

    resp = await db_client.post(f"/novels/{novel_id}/chain", json={"model": "opus", "expectedCost": 170, "maxBatches": 1})

    assert (resp.status_code, resp.json()["detail"]["code"]) == (403, "NOVEL_MODEL_NOT_ALLOWED")
    assert await _novel_ledger(db_session, owner_id) == []
    assert await db_session.scalar(sa.select(sa.func.count()).select_from(NovelJob).where(NovelJob.novel_id == novel_id)) == 0
    assert enqueued == []


async def test_poll_reads_the_planned_batches_from_the_row_not_from_current_settings(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    enqueued: list[uuid.UUID],
) -> None:
    """화 수 상한이 배포로 바뀌어도 진행 표시의 분모는 차감할 때 정한 묶음 수다. 차감액을 지금 상한으로 나누면 2 가 6 이
    된다."""
    _, novel_id, _ = await _chain_novel(db_client, db_session, monkeypatch, turns=4)
    monkeypatch.setattr(settings, "novelize_chapter_max_turns", 2)
    parent_id = await _start(db_client, novel_id, max_batches=2)
    monkeypatch.setattr(settings, "novelize_k_max_gemini", 1)

    polled = (await db_client.get(f"/novels/{novel_id}/jobs/{parent_id}")).json()

    assert (polled["kind"], polled["completedBatches"], polled["plannedBatches"]) == ("chain_generate", 0, 2)


# ── 실행 ────────────────────────────────────────────────────────────────────
async def test_chain_makes_each_batch_and_refunds_the_unused_share(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    enqueued: list[uuid.UUID],
) -> None:
    """묶음 둘(5턴, 턴 상한 2 — 마지막 한 턴은 다음 번 몫)을 경계 제안이 고른 끝으로 하나씩 만든다. 화 수 상한(3화)씩
    미리 받았지만 묶음마다 한 화씩 썼으므로 4화 몫을 돌려준다. 폴링 화면이 이동할 첫 묶음의 첫 화가 부모에 남는다."""
    room, novel_id, owner_id = await _chain_novel(db_client, db_session, monkeypatch, turns=4)
    monkeypatch.setattr(settings, "novelize_chapter_max_turns", 2)
    parent_id = await _start(db_client, novel_id, max_batches=2)
    fake = _ChainLLM(end_turns=[1, None])

    await runner.run_chain(_factory(db_session), fake, parent_id)

    parent = await _job(db_session, parent_id)
    assert (parent.status, parent.consumed_amount, parent.refunded_amount) == ("succeeded", 80, 160)
    assert parent.refunded_at is not None
    children = await _children(db_session, parent_id)
    assert [(c.status, c.charged_amount, c.model, c.episode_count_target) for c in children] == [
        ("succeeded", 0, "gemini", 1),
        ("succeeded", 0, "gemini", 1),
    ]
    messages = await _room_messages(db_session, room.room_id)
    # 첫 묶음은 제안이 고른 첫 턴(오프닝)에서, 둘째는 제안 실패로 턴 상한 끝(둘째 턴 이후 두 턴)에서 끊는다.
    assert [(c.start_message_id, c.end_message_id) for c in children] == [
        (messages[0].id, messages[0].id),
        (messages[1].id, room.turns[2][1].id),
    ]
    batches = await _batches(db_session, novel_id)
    assert [b.assistant_message_count for b in batches] == [1, 2]
    first_chapter = await db_session.scalar(sa.select(NovelChapter.id).where(NovelChapter.batch_id == batches[0].id))
    assert (parent.batch_id, parent.chapter_id) == (batches[0].id, first_chapter)
    assert await _novel_ledger(db_session, owner_id) == [("novelize_spend", -240), ("novelize_refund", 160)]
    await _assert_lots_match_balance(db_session, owner_id)
    polled = (await db_client.get(f"/novels/{novel_id}/jobs/{parent_id}")).json()
    assert (polled["completedBatches"], polled["plannedBatches"], polled["refundedAmount"]) == (2, 2, 160)


async def test_consumed_share_is_the_smaller_of_the_planned_and_delivered_episodes(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    enqueued: list[uuid.UUID],
) -> None:
    """화 목표 길이를 1자로 줄여 묶음마다 화 수 상한(3화)을 계획하고 차감한다. 차감 뒤 상한 설정이 2 로 내려가 자식의
    목표는 2화다. 첫 묶음은 한 화만 내 한 화 몫, 둘째는 세 화를 내도 목표 두 화 몫만 쓴다(많이 낸 화는 단일 묶음처럼
    추가로 받지 않는다) — 낸 240 중 120 을 쓰고 120 을 돌려준다. 세 화는 지금 설정(2)을 넘지만 부모가 차감할 때 고정한
    상한(3) 안이라 받는다."""
    _, novel_id, owner_id = await _chain_novel(db_client, db_session, monkeypatch, turns=3)
    monkeypatch.setattr(settings, "novelize_chapter_max_turns", 2)
    monkeypatch.setattr(settings, "novelize_episode_target_chars", 1)
    parent_id = await _start(db_client, novel_id)
    monkeypatch.setattr(settings, "novelize_k_max_gemini", 2)
    fake = _ChainLLM([_batch_output(_BODY), _batch_output(_BODY, _BODY, _BODY)])

    await runner.run_chain(_factory(db_session), fake, parent_id)

    parent = await _job(db_session, parent_id)
    assert [c.episode_count_target for c in await _children(db_session, parent_id)] == [2, 2]
    assert (parent.status, parent.charged_amount, parent.consumed_amount, parent.refunded_amount) == (
        "succeeded",
        240,
        120,
        120,
    )
    assert await _chapter_count(db_session, novel_id) == 4
    await _assert_lots_match_balance(db_session, owner_id)


async def test_child_episode_target_and_accepted_count_stay_within_the_cap_fixed_at_charge_time(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    enqueued: list[uuid.UUID],
) -> None:
    """차감은 묶음마다 그때의 화 수 상한(3)만큼 받았다. 그 뒤 상한이 5 로 올라도 자식은 3화를 넘겨 계획하지 않는다 —
    넘기면 쓴 몫이 낸 돈을 넘을 수 있다. 받는 화 수의 상한도 차감 때 고정한 3 이다: 다섯 화를 내면 지금 설정(5) 안이어도
    형식 위반으로 실패하고, 부모는 아무것도 쓰지 않아 낸 금액을 모두 돌려준다."""
    _, novel_id, owner_id = await _chain_novel(db_client, db_session, monkeypatch, turns=1)
    monkeypatch.setattr(settings, "novelize_episode_target_chars", 1)
    parent_id = await _start(db_client, novel_id)
    monkeypatch.setattr(settings, "novelize_k_max_gemini", 5)
    fake = _ChainLLM([_batch_output(*[_BODY] * 5)])

    await runner.run_chain(_factory(db_session), fake, parent_id)

    parent = await _job(db_session, parent_id)
    (child,) = await _children(db_session, parent_id)
    assert (child.episode_count_target, child.status, child.failure_code) == (3, "failed", "malformed")
    assert (parent.status, parent.failure_code, parent.charged_amount, parent.consumed_amount) == (
        "failed",
        "malformed",
        120,
        0,
    )
    assert parent.refunded_amount == 120
    assert await _batches(db_session, novel_id) == []
    assert await _chapter_count(db_session, novel_id) == 0
    assert await _novel_ledger(db_session, owner_id) == [("novelize_spend", -120), ("novelize_refund", 120)]
    await _assert_lots_match_balance(db_session, owner_id)


async def test_a_failed_batch_stops_the_chain_and_refunds_the_rest(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    enqueued: list[uuid.UUID],
) -> None:
    """셋 중 둘째 묶음이 실패하면 셋째는 만들지 않고, 부모는 그 사유로 실패해 첫 묶음이 쓴 한 화 몫을 뺀 나머지를
    돌려준다. 자식은 차감 0 이라 환불 기록이 없다."""
    _, novel_id, owner_id = await _chain_novel(db_client, db_session, monkeypatch, turns=5)
    monkeypatch.setattr(settings, "novelize_chapter_max_turns", 2)
    parent_id = await _start(db_client, novel_id)
    fake = _ChainLLM(errors={1: LLMClientError("모델 오류")})

    await runner.run_chain(_factory(db_session), fake, parent_id)

    parent = await _job(db_session, parent_id)
    assert (parent.status, parent.failure_code, parent.consumed_amount, parent.refunded_amount) == (
        "failed",
        "llm_error",
        40,
        360 - 40,
    )
    children = await _children(db_session, parent_id)
    assert [(c.status, c.refunded_at, c.refunded_amount) for c in children] == [
        ("succeeded", None, None),
        ("failed", None, None),
    ]
    assert len(fake.generate_calls) == 2
    assert await _novel_ledger(db_session, owner_id) == [("novelize_spend", -360), ("novelize_refund", 320)]
    await _assert_lots_match_balance(db_session, owner_id)


async def test_a_chain_that_finds_nothing_left_to_write_fails_with_a_full_refund(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    enqueued: list[uuid.UUID],
) -> None:
    """차감 뒤 실행 전에 남은 대화가 사라져 묶음을 하나도 못 만들었다. 성공 행의 환불은 부분 환불뿐이라 전액 환불은
    실패로 끝낸다."""
    room, novel_id, owner_id = await _chain_novel(db_client, db_session, monkeypatch, turns=2)
    parent_id = await _start(db_client, novel_id)
    messages = await _room_messages(db_session, room.room_id)
    await _add_chapter(db_session, novel_id, room, messages[0], messages[-1])

    await runner.run_chain(_factory(db_session), _ChainLLM(), parent_id)

    parent = await _job(db_session, parent_id)
    assert (parent.status, parent.failure_code, parent.refunded_amount) == ("failed", "source_changed", 120)
    assert await _children(db_session, parent_id) == []
    assert await _novel_ledger(db_session, owner_id) == [("novelize_spend", -120), ("novelize_refund", 120)]


async def test_auto_boundaries_do_not_count_toward_the_hourly_proposal_limit(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    enqueued: list[uuid.UUID],
    llm: _ChainLLM,
) -> None:
    """사용자가 누른 것은 연쇄 한 번이다. 묶음마다 부르는 경계 제안을 시간당 제안 상한에 세면 상한 1 에서 그다음 제안이
    429 가 된다."""
    _, novel_id, _ = await _chain_novel(db_client, db_session, monkeypatch, turns=3)
    monkeypatch.setattr(settings, "novelize_chapter_max_turns", 2)
    monkeypatch.setattr(settings, "novelize_proposal_hourly_limit", 1)
    parent_id = await _start(db_client, novel_id, max_batches=1)

    await runner.run_chain(_factory(db_session), llm, parent_id)

    assert (await _job(db_session, parent_id)).status == "succeeded"
    assert len(llm.boundary_calls) == 1
    assert (await db_client.post(f"/novels/{novel_id}/chapter-proposal", json={"model": "gemini"})).status_code == 200


async def test_opus_chain_children_never_exceed_its_turn_cap_and_become_the_last_model(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    enqueued: list[uuid.UUID],
) -> None:
    """45턴을 Opus(턴 상한 20)로 잇는다. 경계 제안이 실패하거나 범위 밖 번호를 내도 자식의 끝은 그 모델의 턴 상한
    안이다 — Gemini 상한(45)이 끼면 Opus 작업 상한 근거가 깨진다. 끝난 뒤 상세의 직전 모델은 연쇄의 모델이다."""
    _, novel_id, _ = await _chain_novel(db_client, db_session, monkeypatch, turns=44, premium=True)
    parent_id = await _start(db_client, novel_id, "opus")
    fake = _ChainLLM(end_turns=[None, 99, None])

    await runner.run_chain(_factory(db_session), fake, parent_id)

    parent = await _job(db_session, parent_id)
    assert (parent.status, parent.charged_amount, parent.planned_batches) == ("succeeded", 3 * 170, 3)
    assert [b.assistant_message_count for b in await _batches(db_session, novel_id)] == [20, 20, 5]
    assert {usage.model for usage in fake.generate_calls} == {"opus"}
    detail = (await db_client.get(f"/novels/{novel_id}")).json()
    assert detail["lastChapterModel"] == "opus"


async def test_children_keep_the_parents_model_after_premium_access_is_revoked(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    enqueued: list[uuid.UUID],
) -> None:
    """값을 낸 모델로 끝낸다 — 차감 뒤 허용을 거둬도 자식은 부모 모델 그대로다."""
    _, novel_id, _ = await _chain_novel(db_client, db_session, monkeypatch, turns=2, premium=True)
    parent_id = await _start(db_client, novel_id, "sonnet")
    monkeypatch.setattr(settings, "novelize_premium_models_enabled", False)
    fake = _ChainLLM()

    await runner.run_chain(_factory(db_session), fake, parent_id)

    assert (await _job(db_session, parent_id)).status == "succeeded"
    assert [c.model for c in await _children(db_session, parent_id)] == ["sonnet"]
    assert [usage.model for usage in fake.generate_calls] == ["sonnet"]


# ── 만료·경합·시간 상한 ─────────────────────────────────────────────────────
async def test_parent_expiring_while_a_batch_is_written_discards_that_batch(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    enqueued: list[uuid.UUID],
) -> None:
    """둘째 묶음을 쓰는 사이 만료 정리가 부모를 끝낸다. 부모는 첫 묶음이 쓴 몫을 뺀 나머지를 돌려받고, 돌던 자식도
    함께 실패하며(자식 heartbeat 는 살아 있었다), 늦게 온 둘째 결과는 저장되지 않는다 — 환불된 돈으로 묶음을 받지 않는다."""
    _, novel_id, owner_id = await _chain_novel(db_client, db_session, monkeypatch, turns=3)
    monkeypatch.setattr(settings, "novelize_chapter_max_turns", 2)
    parent_id = await _start(db_client, novel_id)
    factory = _factory(db_session)

    async def cleanup_wins() -> None:
        async with factory() as s:
            await _age_heartbeat(s, parent_id)
            assert await runner.expire_stale_jobs(s, novel_id=novel_id) == 1
            await s.commit()

    await runner.run_chain(factory, _ChainLLM(during={1: cleanup_wins}), parent_id)

    parent = await _job(db_session, parent_id)
    assert (parent.status, parent.failure_code, parent.consumed_amount, parent.refunded_amount) == (
        "failed",
        "expired",
        40,
        200,
    )
    assert [(c.status, c.failure_code) for c in await _children(db_session, parent_id)] == [
        ("succeeded", None),
        ("failed", "expired"),
    ]
    assert len(await _batches(db_session, novel_id)) == 1
    assert await _novel_ledger(db_session, owner_id) == [("novelize_spend", -240), ("novelize_refund", 200)]
    await _assert_lots_match_balance(db_session, owner_id)


async def test_batch_finishing_after_its_parent_ended_elsewhere_is_discarded(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    enqueued: list[uuid.UUID],
) -> None:
    """자식을 모르는 경로(옛 판 코드의 환불처럼 부모에 환불 시각만 찍는다)가 부모만 끝냈다. 자식 자신의 전이는 통과해도
    부모가 실행 중이 아니므로 결과를 버리고 실패한다 — 공짜 묶음이 남지 않고 끝난 부모의 소비액도 그대로다."""
    _, novel_id, _ = await _chain_novel(db_client, db_session, monkeypatch, turns=2)
    parent_id = await _start(db_client, novel_id)
    factory = _factory(db_session)

    async def parent_ended_without_children() -> None:
        async with factory() as s:
            await s.execute(
                sa.update(NovelJob)
                .where(NovelJob.id == parent_id)
                .values(status="failed", failure_code="expired", refunded_at=sa.func.now(), finished_at=sa.func.now())
            )
            await s.commit()

    await runner.run_chain(factory, _ChainLLM(during={0: parent_ended_without_children}), parent_id)

    parent = await _job(db_session, parent_id)
    assert (parent.status, parent.consumed_amount) == ("failed", 0)
    assert [(c.status, c.failure_code) for c in await _children(db_session, parent_id)] == [("failed", "expired")]
    assert await _batches(db_session, novel_id) == []


async def test_a_batch_saved_before_the_parent_expires_is_kept_and_not_refunded(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    enqueued: list[uuid.UUID],
) -> None:
    """반대 순서 — 첫 묶음 저장이 먼저 커밋되고, 다음 묶음의 경계를 고르는 사이 부모가 만료된다. 저장된 묶음은 남고
    부모 환불은 그 묶음이 쓴 몫을 빼며, 끝난 부모 아래 새 자식은 생기지 않는다."""
    _, novel_id, owner_id = await _chain_novel(db_client, db_session, monkeypatch, turns=3)
    monkeypatch.setattr(settings, "novelize_chapter_max_turns", 2)
    parent_id = await _start(db_client, novel_id)
    factory = _factory(db_session)
    fake = _ChainLLM()
    boundary = fake.generate_structured_with_instruction

    async def expire_before_second_boundary(prompt: str, response_schema: type[T], **kwargs: Any) -> T:
        if fake.boundary_calls:
            async with factory() as s:
                await _age_heartbeat(s, parent_id)
                await runner.expire_stale_jobs(s, novel_id=novel_id)
                await s.commit()
        return await boundary(prompt, response_schema, **kwargs)

    monkeypatch.setattr(fake, "generate_structured_with_instruction", expire_before_second_boundary)

    await runner.run_chain(factory, fake, parent_id)

    parent = await _job(db_session, parent_id)
    assert (parent.status, parent.consumed_amount, parent.refunded_amount) == ("failed", 40, 200)
    assert [c.status for c in await _children(db_session, parent_id)] == ["succeeded"]
    assert len(await _batches(db_session, novel_id)) == 1
    await _assert_lots_match_balance(db_session, owner_id)


async def test_chain_over_its_overall_time_cap_fails_and_ends_the_running_batch(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    enqueued: list[uuid.UUID],
) -> None:
    """heartbeat 가 살아 있어도 전체 상한을 넘으면 부모는 실패하고 돌던 자식도 끝난다 — 걸린 연쇄가 소설을 영영 진행
    중으로 잠그지 않는다. 상한은 차감 때 정한 묶음 수로 계산한다."""
    _, novel_id, owner_id = await _chain_novel(db_client, db_session, monkeypatch, turns=2)
    parent_id = await _start(db_client, novel_id)
    asked: list[int] = []

    def tiny_cap(planned: int) -> float:
        asked.append(planned)
        return 0.3

    monkeypatch.setattr(runner, "chain_timeout_seconds", tiny_cap)

    async def stall() -> None:
        await asyncio.sleep(30)

    await runner.run_chain(_factory(db_session), _ChainLLM(during={0: stall}), parent_id)

    assert asked == [1]
    parent = await _job(db_session, parent_id)
    assert (parent.status, parent.failure_code, parent.refunded_amount) == ("failed", "timeout", 120)
    assert [(c.status, c.failure_code) for c in await _children(db_session, parent_id)] == [("failed", "timeout")]
    assert await _novel_ledger(db_session, owner_id) == [("novelize_spend", -120), ("novelize_refund", 120)]
    detail = (await db_client.get(f"/novels/{novel_id}")).json()
    assert detail["activeJob"] is None


def test_overall_time_cap_grows_by_a_job_cap_and_a_boundary_call_per_batch_plus_a_fixed_margin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """묶음마다 경계 제안 한 번과 자식 작업 하나가 돈다 — 경계 제안 몫이 고정 여유에 묻혀 있으면 묶음이 많을수록 여유가
    모자라 마지막 묶음이 끊긴다."""
    monkeypatch.setattr(settings, "novelize_job_timeout_seconds", 360)
    monkeypatch.setattr(settings, "gemini_novelize_boundary_timeout_ms", 30_000)
    monkeypatch.setattr(settings, "novelize_chain_timeout_margin_seconds", 60)

    assert [runner.chain_timeout_seconds(n) for n in (1, 5)] == [450, 2010]


async def test_chain_cut_by_a_restart_is_refunded_by_expiry_minus_what_it_used(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    enqueued: list[uuid.UUID],
) -> None:
    """배포가 프로세스 안 태스크를 끊으면 이어서 돌리지 않는다. heartbeat 가 멈춘 부모를 만료 정리가 실패시키며 쓴 몫을
    뺀 나머지를 돌려주고, 끊긴 자식도 함께 끝낸다."""
    _, novel_id, owner_id = await _chain_novel(db_client, db_session, monkeypatch, turns=3)
    monkeypatch.setattr(settings, "novelize_chapter_max_turns", 2)
    parent_id = await _start(db_client, novel_id)
    second_started = asyncio.Event()

    async def hang() -> None:
        second_started.set()
        await asyncio.sleep(30)

    task = asyncio.ensure_future(runner.run_chain(_factory(db_session), _ChainLLM(during={1: hang}), parent_id))
    await asyncio.wait_for(second_started.wait(), 10)
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task
    children = await _children(db_session, parent_id)
    assert [c.status for c in children] == ["succeeded", "running"]
    for job_id in (parent_id, children[1].id):
        await _age_heartbeat(db_session, job_id)

    await runner.expire_stale_jobs(db_session, novel_id=novel_id)
    await db_session.commit()

    parent = await _job(db_session, parent_id)
    assert (parent.status, parent.failure_code, parent.consumed_amount, parent.refunded_amount) == (
        "failed",
        "expired",
        40,
        200,
    )
    assert [c.status for c in await _children(db_session, parent_id)] == ["succeeded", "failed"]
    assert await _novel_ledger(db_session, owner_id) == [("novelize_spend", -240), ("novelize_refund", 200)]
    await _assert_lots_match_balance(db_session, owner_id)
