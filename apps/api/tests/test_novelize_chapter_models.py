"""소설 장의 글쓰기 모델 — 장 생성·재생성 요청이 고른 모델, 그 모델의 가격, 작업에 적힌 모델로 도는 실행.

라우트 시험은 작업을 띄우는 함수(`enqueue_job`)를 기록용으로 바꿔 끼우고, 실행은 그 작업 id 로 `run_job` 을 직접
기다린다(`test_novelize_runner.py` 와 같은 세션 팩토리). 상위 모델 장은 클로버가 많이 들어 소설 셋업 뒤에 잔액을 더한다."""

import asyncio
import uuid
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import anthropic
import httpx
import httpx2
import pytest
import sqlalchemy as sa
from factories import (
    _enable_chat_premium,
    Room,
    _add_chapter,
    _allow_novel_premium,
    _batch_output,
    _clear_llm_override,
    _novel_ledger,
    _novel_setup,
    _override_llm_client,
    _queue_job,
    _room_messages,
)
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from api.core import clover
from api.core.config import settings
from api.chat.prompt_builder import PromptLane, load_active_prompt_set
from api.db.models import Novel, NovelJob
from api.db.models.prompt import PromptSection, PromptSet
from api.llm import bedrock as bedrock_module
from api.llm.bedrock import BedrockLLMClient
from api.llm.chat_models import ChatModelId
from api.llm.client import LLMCallContext, LLMClient, T
from api.llm.routing import RoutingLLMClient
from api.novelize import router as novelize_router
from api.novelize import runner
from api.novelize.prompts import NovelizeBoundaryResult

pytestmark = pytest.mark.usefixtures("novel_prices_for_flow_tests")

_BODY = "비가 내리는 저녁이었다. 서진은 가방을 내려놓고 창가에 섰다.\n\n" + "도윤이 잔을 밀어 주었다. " * 20


class _ModelLLM(LLMClient):
    """장 생성은 `_BODY` 한 화짜리 출력을 흘리고 호출(프롬프트·지시문·사용량 귀속)을 적는다. 경계 제안은 마지막 후보
    턴을 고른다."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str | None, LLMCallContext]] = []
        self.boundary_calls = 0

    async def generate(
        self,
        prompt: str,
        system_instruction: str | None = None,
        stop_sequences: list[str] | None = None,
        *,
        usage: LLMCallContext,
    ) -> AsyncIterator[str]:
        self.calls.append((prompt, system_instruction, usage))
        yield _batch_output(_BODY)

    async def generate_structured(
        self, prompt: str, response_schema: Any, images: Any = None, *, usage: LLMCallContext
    ) -> Any:
        raise AssertionError("소설화는 지시문 없는 구조화 호출을 쓰지 않는다")

    async def generate_structured_with_instruction(
        self, prompt: str, response_schema: type[T], *, system_instruction: str, usage: LLMCallContext
    ) -> T:
        assert response_schema is NovelizeBoundaryResult
        self.boundary_calls += 1
        return response_schema.model_validate({"end_turn": 1, "reason": "끝"})


@pytest.fixture
def llm() -> Iterator[_ModelLLM]:
    fake = _ModelLLM()
    _override_llm_client(fake)
    yield fake
    _clear_llm_override()


@pytest.fixture
def enqueued(monkeypatch: pytest.MonkeyPatch) -> list[uuid.UUID]:
    seen: list[uuid.UUID] = []

    async def record(_factory: Any, _llm: Any, job_id: uuid.UUID) -> None:
        seen.append(job_id)

    monkeypatch.setattr(novelize_router, "enqueue_job", record)
    return seen


@pytest.fixture(autouse=True)
def _slow_heartbeat(monkeypatch: pytest.MonkeyPatch) -> None:
    # 실행 시험의 세션 팩토리가 테스트 커넥션 하나에 묶여 있어 heartbeat 가 끼면 그 커넥션에서 부딪힌다.
    monkeypatch.setattr(settings, "novelize_heartbeat_interval_seconds", 3600)


def _factory(db_session: AsyncSession) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(bind=db_session.bind, expire_on_commit=False, join_transaction_mode="create_savepoint")


async def _novel(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, *, premium: bool
) -> tuple[Room, uuid.UUID, uuid.UUID]:
    """소설화를 허용한 3턴 방의 소설. 잔액은 600 클로버이고, `premium` 이면 소설 상위 모델도 허용한다."""
    room, novel_id = await _novel_setup(db_client, db_session, monkeypatch)
    owner_id = (await db_session.get_one(Novel, novel_id)).user_id
    await clover.grant(db_session, user_id=owner_id, amount=500, kind="admin_grant")
    await db_session.commit()
    if premium:
        await _allow_novel_premium(db_session, monkeypatch, owner_id)
    return room, novel_id, owner_id


async def _create(
    db_client: httpx.AsyncClient, novel_id: uuid.UUID, room: Room, *, cost: int, model: str | None
) -> httpx.Response:
    payload: dict[str, Any] = {"endMessageId": str(room.turns[1][1].id), "expectedCost": cost}
    if model is not None:
        payload["model"] = model
    return await db_client.post(f"/novels/{novel_id}/chapters", json=payload)


async def _regenerate(
    db_client: httpx.AsyncClient, novel_id: uuid.UUID, chapter_id: uuid.UUID, *, cost: int, model: str | None
) -> httpx.Response:
    payload: dict[str, Any] = {"expectedCost": cost}
    if model is not None:
        payload["model"] = model
    return await db_client.post(f"/novels/{novel_id}/chapters/{chapter_id}/regenerate", json=payload)


async def _jobs(db: AsyncSession, novel_id: uuid.UUID) -> list[NovelJob]:
    rows = await db.scalars(
        sa.select(NovelJob).where(NovelJob.novel_id == novel_id).execution_options(populate_existing=True)
    )
    return list(rows.all())


# ── 장 생성·재생성 요청 ─────────────────────────────────────────────────────
async def test_a_premium_chapter_is_charged_at_its_model_price_and_the_job_records_the_model(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    llm: _ModelLLM,
    enqueued: list[uuid.UUID],
) -> None:
    room, novel_id, owner_id = await _novel(db_client, db_session, monkeypatch, premium=True)

    resp = await _create(db_client, novel_id, room, cost=105, model="sonnet")

    assert resp.status_code == 202, resp.text
    body = resp.json()
    assert (body["model"], body["chargedAmount"]) == ("sonnet", 105)
    (job,) = await _jobs(db_session, novel_id)
    assert (job.model, job.charged_amount, job.status) == ("sonnet", 105, "queued")
    assert enqueued == [job.id]
    assert await _novel_ledger(db_session, owner_id) == [("novelize_spend", -105)]


async def test_a_premium_regenerate_is_charged_at_its_model_price(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    llm: _ModelLLM,
    enqueued: list[uuid.UUID],
) -> None:
    """상위 모델은 생성·재생성이 같은 값이다. 재생성 시험에 Opus 를 쓰는 것은 두 상위 모델의 가격이 서로 섞이지 않는지도
    함께 보려는 것이다."""
    room, novel_id, owner_id = await _novel(db_client, db_session, monkeypatch, premium=True)
    messages = await _room_messages(db_session, room.room_id)
    chapter = await _add_chapter(db_session, novel_id, room, messages[0], room.turns[1][1])

    resp = await _regenerate(db_client, novel_id, chapter.id, cost=170, model="opus")

    assert resp.status_code == 202, resp.text
    assert (resp.json()["model"], resp.json()["chargedAmount"]) == ("opus", 170)
    (job,) = await _jobs(db_session, novel_id)
    assert (job.kind, job.model, job.charged_amount) == ("chapter_regenerate", "opus", 170)
    assert await _novel_ledger(db_session, owner_id) == [("novelize_spend", -170)]


async def test_a_request_without_a_model_is_a_gemini_chapter_at_the_gemini_price_and_needs_no_premium_access(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    llm: _ModelLLM,
    enqueued: list[uuid.UUID],
) -> None:
    """옛 화면은 `model` 을 보내지 않는다 — 배포가 어긋나 있는 동안에도 지금처럼 Gemini 장이 돼야 한다. Gemini 를 직접
    고르는 것도 상위 모델 허용 없이 된다."""
    room, novel_id, owner_id = await _novel(db_client, db_session, monkeypatch, premium=False)
    monkeypatch.setattr(clover, "NOVELIZE_EPISODE_COST", 31)
    messages = await _room_messages(db_session, room.room_id)
    chapter = await _add_chapter(db_session, novel_id, room, messages[0], room.turns[1][1])

    regenerated = await _regenerate(db_client, novel_id, chapter.id, cost=31, model="gemini")
    await db_session.execute(sa.update(NovelJob).values(status="succeeded"))
    await db_session.commit()
    created = await db_client.post(
        f"/novels/{novel_id}/chapters", json={"endMessageId": str(room.turns[3][1].id), "expectedCost": 31}
    )

    assert regenerated.status_code == 202, regenerated.text
    assert created.status_code == 202, created.text
    assert (regenerated.json()["model"], created.json()["model"]) == ("gemini", "gemini")
    jobs = {job.kind: job for job in await _jobs(db_session, novel_id)}
    assert (jobs["chapter_regenerate"].model, jobs["chapter_regenerate"].charged_amount) == ("gemini", 31)
    assert (jobs["chapter_generate"].model, jobs["chapter_generate"].charged_amount) == ("gemini", 31)
    assert await _novel_ledger(db_session, owner_id) == [("novelize_spend", -31), ("novelize_spend", -31)]


@pytest.mark.parametrize(
    "missing",
    [
        pytest.param("switch", id="switch-off"),
        pytest.param("allowlist", id="not-allowlisted"),
        pytest.param("grant", id="no-grant-row"),
        pytest.param("chat-only", id="chat-premium-only"),
    ],
)
async def test_a_premium_model_without_novel_premium_access_is_403_before_charging(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    llm: _ModelLLM,
    enqueued: list[uuid.UUID],
    missing: str,
) -> None:
    """장 요청의 모델은 그때 고르는 값이라 쓸 수 없으면 Gemini 로 바꿔 받지 않고 거절한다 — 사용자가 확인한 것은 그
    모델과 그 가격이다. 채팅 상위 모델 스위치는 소설 장을 열지 않는다(판정이 기능마다 따로다)."""
    room, novel_id, owner_id = await _novel(db_client, db_session, monkeypatch, premium=missing != "chat-only")
    if missing == "switch":
        monkeypatch.setattr(settings, "novelize_premium_models_enabled", False)
    elif missing == "allowlist":
        monkeypatch.setattr(settings, "novelize_premium_model_allowlist", [])
    elif missing == "grant":
        await db_session.execute(sa.text("DELETE FROM user_feature_grants WHERE feature = 'novelize_premium_models'"))
        await db_session.commit()
    else:
        _enable_chat_premium(monkeypatch)
    messages = await _room_messages(db_session, room.room_id)
    chapter = await _add_chapter(db_session, novel_id, room, messages[0], room.turns[1][1])

    created = await db_client.post(
        f"/novels/{novel_id}/chapters",
        json={"endMessageId": str(room.turns[3][1].id), "expectedCost": 105, "model": "sonnet"},
    )
    regenerated = await _regenerate(db_client, novel_id, chapter.id, cost=170, model="opus")

    for resp in (created, regenerated):
        assert resp.status_code == 403, resp.text
        assert resp.json()["detail"] == {"code": "NOVEL_MODEL_NOT_ALLOWED"}
    assert await _jobs(db_session, novel_id) == []
    assert await _novel_ledger(db_session, owner_id) == []
    assert enqueued == []


@pytest.mark.parametrize(
    ("model", "current"), [pytest.param("opus", 170, id="opus"), pytest.param(None, 40, id="gemini-by-default")]
)
async def test_the_price_check_uses_the_chosen_models_price(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    llm: _ModelLLM,
    enqueued: list[uuid.UUID],
    model: str | None,
    current: int,
) -> None:
    """Gemini 가격으로 확인한 화면이 상위 모델을 보내면(또는 그 반대) 확인한 금액과 차감액이 다르다 — 409 가 지금 그
    모델의 가격을 알려 준다.

    다시 만들기는 금액이 묶음의 화 수로 정해져 사용자 잠금 뒤에 판정하고, 그 거절은 요청 세션을 롤백한다. 이 시험의
    요청 세션은 테스트 트랜잭션 자체라 그 롤백이 셋업까지 지우므로, 다시 만들기 요청을 맨 끝에 한 번만 보낸다(원장이
    비는 것은 과금 시험이 따로 본다)."""
    room, novel_id, owner_id = await _novel(db_client, db_session, monkeypatch, premium=True)
    messages = await _room_messages(db_session, room.room_id)
    chapter_id = (await _add_chapter(db_session, novel_id, room, messages[0], room.turns[1][1])).id

    created = await db_client.post(
        f"/novels/{novel_id}/chapters",
        json={"endMessageId": str(room.turns[3][1].id), "expectedCost": 40, "model": "sonnet"},
    )
    assert created.status_code == 409 and created.json()["detail"] == {
        "code": "NOVELIZE_PRICE_CHANGED",
        "currentCost": 105,
    }
    assert await _novel_ledger(db_session, owner_id) == []

    regenerated = await _regenerate(db_client, novel_id, chapter_id, cost=105, model=model)

    assert regenerated.status_code == 409 and regenerated.json()["detail"] == {
        "code": "NOVELIZE_PRICE_CHANGED",
        "currentCost": current,
    }


@pytest.mark.parametrize("model", ["gpt", "haiku"])  # haiku 는 판정 문안 전용 id 라 글을 쓰지 않는다
async def test_a_model_outside_the_registry_is_422(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    llm: _ModelLLM,
    enqueued: list[uuid.UUID],
    model: str,
) -> None:
    room, novel_id, _ = await _novel(db_client, db_session, monkeypatch, premium=True)

    resp = await _create(db_client, novel_id, room, cost=105, model=model)

    assert resp.status_code == 422, resp.text
    assert await _jobs(db_session, novel_id) == []


# ── 금액·직전 모델 표시 ─────────────────────────────────────────────────────
def _expected_models(*, premium: bool) -> list[dict[str, Any]]:
    """두 금액 칸은 이제 화 하나의 값이고 생성·다시 만들기가 같다."""
    gemini = {"id": "gemini", "name": "Gemini", "chapterGenerate": 31, "chapterRegenerate": 31}
    if not premium:
        return [gemini]
    return [
        gemini,
        {"id": "sonnet", "name": "Claude Sonnet 5.5", "chapterGenerate": 106, "chapterRegenerate": 106},
        {"id": "opus", "name": "Claude Opus 5.5", "chapterGenerate": 171, "chapterRegenerate": 171},
    ]


def _distinct_prices(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(clover, "NOVELIZE_EPISODE_COST", 31)
    monkeypatch.setattr(clover, "NOVELIZE_EPISODE_COST_SONNET", 106)
    monkeypatch.setattr(clover, "NOVELIZE_EPISODE_COST_OPUS", 171)


@pytest.mark.parametrize("premium", [pytest.param(True, id="premium"), pytest.param(False, id="gemini-only")])
async def test_detail_and_proposal_list_episode_prices_per_model_only_with_novel_premium_access(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    llm: _ModelLLM,
    premium: bool,
) -> None:
    """기존 금액 칸(`prices`·`cost`)은 그대로 Gemini 값이고, 모델별 목록은 덧붙인다 — 옛 화면이 보는 칸이 바뀌지 않는다."""
    _, novel_id, _ = await _novel(db_client, db_session, monkeypatch, premium=premium)
    _distinct_prices(monkeypatch)

    detail = await db_client.get(f"/novels/{novel_id}")
    proposal = await db_client.post(f"/novels/{novel_id}/chapter-proposal")

    assert detail.status_code == 200, detail.text
    assert proposal.status_code == 200, proposal.text
    assert detail.json()["chapterModels"] == _expected_models(premium=premium)
    assert proposal.json()["chapterModels"] == _expected_models(premium=premium)
    assert (detail.json()["prices"]["chapterGenerate"], proposal.json()["cost"]) == (31, 31)


async def _finished_job(
    db: AsyncSession, novel_id: uuid.UUID, user_id: uuid.UUID, *, model: str | None, status: str, kind: str, at: int
) -> None:
    db.add(
        NovelJob(
            novel_id=novel_id,
            user_id=user_id,
            kind=kind,
            status=status,
            model=model,
            charged_amount=0,
            created_at=datetime(2026, 10, 1, tzinfo=UTC) + timedelta(minutes=at),
        )
    )
    await db.flush()


async def test_detail_last_chapter_model_is_the_latest_succeeded_chapter_job_while_it_is_allowed(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, llm: _ModelLLM
) -> None:
    """모달의 기본값은 그 소설이 직전에 쓴 모델이다. 실패한 장(환불됨)과 모델을 고르지 않는 AI 수정은 세지 않고, 그
    모델을 지금 쓸 수 없으면 Gemini 다."""
    _, novel_id, owner_id = await _novel(db_client, db_session, monkeypatch, premium=True)
    before = await db_client.get(f"/novels/{novel_id}")
    await _finished_job(db_session, novel_id, owner_id, model="opus", status="succeeded", kind="chapter_generate", at=0)
    await _finished_job(
        db_session, novel_id, owner_id, model="sonnet", status="succeeded", kind="chapter_regenerate", at=1
    )
    await _finished_job(db_session, novel_id, owner_id, model="gemini", status="failed", kind="chapter_generate", at=2)
    await _finished_job(db_session, novel_id, owner_id, model=None, status="succeeded", kind="ai_edit", at=3)
    await db_session.commit()

    allowed = await db_client.get(f"/novels/{novel_id}")
    monkeypatch.setattr(settings, "novelize_premium_models_enabled", False)
    revoked = await db_client.get(f"/novels/{novel_id}")

    assert before.json()["lastChapterModel"] == "gemini"
    assert allowed.json()["lastChapterModel"] == "sonnet"
    assert revoked.json()["lastChapterModel"] == "gemini"


async def test_an_old_chapter_job_without_a_model_counts_as_gemini_for_the_last_model(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, llm: _ModelLLM
) -> None:
    _, novel_id, owner_id = await _novel(db_client, db_session, monkeypatch, premium=True)
    await _finished_job(db_session, novel_id, owner_id, model="opus", status="succeeded", kind="chapter_generate", at=0)
    await _finished_job(db_session, novel_id, owner_id, model=None, status="succeeded", kind="chapter_generate", at=1)
    await db_session.commit()

    resp = await db_client.get(f"/novels/{novel_id}")

    assert resp.json()["lastChapterModel"] == "gemini"


async def test_job_polling_shows_the_chapter_model_and_no_model_for_an_ai_edit(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, llm: _ModelLLM
) -> None:
    room, novel_id, owner_id = await _novel(db_client, db_session, monkeypatch, premium=True)
    messages = await _room_messages(db_session, room.room_id)
    old = await _queue_job(db_session, novel_id, messages[0], room.turns[1][1])  # 모델 칸이 생기기 전의 장 작업과 같다
    await db_session.execute(sa.update(NovelJob).values(status="succeeded"))
    await _finished_job(db_session, novel_id, owner_id, model=None, status="succeeded", kind="ai_edit", at=0)
    await db_session.commit()
    edit_id = await db_session.scalar(sa.select(NovelJob.id).where(NovelJob.kind == "ai_edit"))

    old_resp = await db_client.get(f"/novels/{novel_id}/jobs/{old.id}")
    edit_resp = await db_client.get(f"/novels/{novel_id}/jobs/{edit_id}")

    assert old_resp.json()["model"] == "gemini"
    assert edit_resp.json()["model"] is None


# ── 실행 ────────────────────────────────────────────────────────────────────
async def test_the_runner_generates_with_the_charged_model_even_after_access_is_revoked(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    llm: _ModelLLM,
    enqueued: list[uuid.UUID],
) -> None:
    """값을 낸 뒤 허용이 회수돼도 그 값의 모델로 쓴다 — 실행 시점에 다시 판정해 Gemini 로 바꾸면 Opus 값을 내고 Gemini
    글을 받는다."""
    room, novel_id, owner_id = await _novel(db_client, db_session, monkeypatch, premium=True)
    resp = await _create(db_client, novel_id, room, cost=170, model="opus")
    assert resp.status_code == 202, resp.text
    monkeypatch.setattr(settings, "novelize_premium_models_enabled", False)
    monkeypatch.setattr(settings, "novelize_premium_model_allowlist", [])

    await runner.run_job(_factory(db_session), llm, enqueued[0])

    (job,) = await _jobs(db_session, novel_id)
    assert job.status == "succeeded"
    ((_, _, usage),) = llm.calls
    assert (usage.call_site, usage.model) == ("novelize_chapter", "opus")
    assert await _novel_ledger(db_session, owner_id) == [("novelize_spend", -170)]


async def test_an_old_chapter_job_without_a_model_runs_on_gemini(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, llm: _ModelLLM
) -> None:
    room, novel_id, _ = await _novel(db_client, db_session, monkeypatch, premium=True)
    messages = await _room_messages(db_session, room.room_id)
    job = await _queue_job(db_session, novel_id, messages[0], room.turns[1][1])

    await runner.run_job(_factory(db_session), llm, job.id)

    ((_, _, usage),) = llm.calls
    assert usage.model == "gemini"


async def _set_instruction(
    db: AsyncSession, *, lane: PromptLane, model: ChatModelId, channel: str, slot: str, body: str
) -> None:
    """(lane, model) 활성 세트의 한 행 문안을 바꾼다 — 어느 세트에서 읽었는지 글자로 가르려는 것이다."""
    _, sections = await load_active_prompt_set(db, lane=lane, model=model)
    row = next(s for s in sections if s.channel == channel and s.slot == slot)
    row.body = body
    await db.commit()


async def test_a_premium_chapter_uses_its_models_novel_chain_and_the_chat_gemini_rating_rule(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    llm: _ModelLLM,
    enqueued: list[uuid.UUID],
) -> None:
    """화 문안은 작업 모델의 소설 체인에서 읽는다 — Sonnet 다시 만들기는 (novel, sonnet) 세트의 지시문, Gemini 생성은
    (novel, gemini) 세트의 지시문이다. 등급 규칙은 모델과 무관하게 원작 종류 채팅 레인의 Gemini 세트에서 붙인다(Claude
    채팅 세트의 등급 규칙이 따로 손질돼 있어도). 세 세트의 문안을 서로 다른 글자로 바꿔 어느 세트를 읽었는지 가른다."""
    room, novel_id, _ = await _novel(db_client, db_session, monkeypatch, premium=True)
    content = (await db_session.get_one(Novel, novel_id)).content_type
    await _set_instruction(
        db_session, lane="novel", model="gemini", channel="novelize_chapter", slot="instruction", body="제미나이 화 지시"
    )
    await _set_instruction(
        db_session, lane="novel", model="sonnet", channel="novelize_chapter", slot="instruction", body="소네트 화 지시"
    )
    await _set_instruction(
        db_session, lane=content, model="gemini", channel="system", slot="rule_rating", body="[수위] 채팅 제미나이"
    )
    await _set_instruction(
        db_session, lane=content, model="sonnet", channel="system", slot="rule_rating", body="[수위] 채팅 소네트"
    )

    first = await _create(db_client, novel_id, room, cost=40, model="gemini")
    await runner.run_job(_factory(db_session), llm, uuid.UUID(first.json()["id"]))
    chapter_id = uuid.UUID((await db_client.get(f"/novels/{novel_id}")).json()["chapters"][0]["id"])
    again = await _regenerate(db_client, novel_id, chapter_id, cost=105, model="sonnet")
    await runner.run_job(_factory(db_session), llm, uuid.UUID(again.json()["id"]))

    (_, gemini_system, gemini_usage), (_, sonnet_system, sonnet_usage) = llm.calls
    assert (gemini_usage.model, sonnet_usage.model) == ("gemini", "sonnet")
    assert gemini_system == "제미나이 화 지시\n\n[수위] 채팅 제미나이"
    assert sonnet_system == "소네트 화 지시\n\n[수위] 채팅 제미나이"
    assert {job.status for job in await _jobs(db_session, novel_id)} == {"succeeded"}


async def test_a_chapter_whose_model_has_no_novel_chain_fails_and_refunds_without_a_fallback(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    llm: _ModelLLM,
    enqueued: list[uuid.UUID],
) -> None:
    """그 모델의 소설 체인이 없으면 Gemini 문안으로 대신 쓰지 않는다 — 값을 낸 모델에 다른 모델용 문안을 보내면 조용히
    다른 글이 나온다. 모델을 부르지 않고 실패·환불한다."""
    room, novel_id, owner_id = await _novel(db_client, db_session, monkeypatch, premium=True)
    resp = await _create(db_client, novel_id, room, cost=170, model="opus")
    assert resp.status_code == 202, resp.text
    opus_sets = sa.select(PromptSet.id).where(PromptSet.lane == "novel", PromptSet.model == "opus")
    await db_session.execute(sa.delete(PromptSection).where(PromptSection.prompt_set_id.in_(opus_sets)))
    await db_session.execute(sa.delete(PromptSet).where(PromptSet.lane == "novel", PromptSet.model == "opus"))
    await db_session.commit()

    await runner.run_job(_factory(db_session), llm, enqueued[0])

    (job,) = await _jobs(db_session, novel_id)
    assert (job.status, job.failure_code) == ("failed", "internal")
    assert llm.calls == []
    assert await _novel_ledger(db_session, owner_id) == [("novelize_spend", -170), ("novelize_refund", 170)]


# ── Bedrock 실패 → 실패 사유·환불 ──────────────────────────────────────────
def _event(kind: str, **fields: Any) -> Any:
    return SimpleNamespace(type=kind, **fields)


def _start() -> Any:
    usage = SimpleNamespace(
        input_tokens=10, cache_read_input_tokens=None, cache_creation_input_tokens=None, output_tokens=1
    )
    return _event("message_start", message=SimpleNamespace(usage=usage))


def _text(text: str) -> Any:
    return _event("content_block_delta", delta=SimpleNamespace(type="text_delta", text=text))


def _stop(reason: str) -> Any:
    usage = SimpleNamespace(
        output_tokens=5, input_tokens=None, cache_read_input_tokens=None, cache_creation_input_tokens=None
    )
    return _event("message_delta", delta=SimpleNamespace(stop_reason=reason), usage=usage)


_REQUEST = httpx2.Request("POST", "https://bedrock-runtime.ap-northeast-2.amazonaws.com")
_HANG = object()


class _UnusedGemini(_ModelLLM):
    async def generate(
        self,
        prompt: str,
        system_instruction: str | None = None,
        stop_sequences: list[str] | None = None,
        *,
        usage: LLMCallContext,
    ) -> AsyncIterator[str]:
        raise AssertionError("상위 모델 장이 Gemini 로 갔다")
        yield ""


@pytest.mark.parametrize(
    ("events", "code"),
    [
        pytest.param([_start(), _text(_BODY), _stop("max_tokens")], "truncated", id="max-tokens"),
        pytest.param([_start(), _stop("end_turn")], "empty", id="empty-body"),
        pytest.param([_start(), _text("짧다."), _stop("end_turn")], "malformed", id="too-short-old-style-body"),
        pytest.param(
            [_start(), _text(_batch_output("짧다.")), _stop("end_turn")], "malformed", id="too-short-episode"
        ),
        pytest.param([_start(), _text("비가 왔다"), _stop("refusal")], "blocked", id="refusal-stop"),
        pytest.param(
            [_start(), _text("I'm sorry, but I can't continue this story."), _stop("end_turn")],
            "refused",
            id="refusal-body",
        ),
        pytest.param(anthropic.APIConnectionError(request=_REQUEST), "llm_error", id="connection"),
        pytest.param(
            anthropic.RateLimitError("throttled", response=httpx2.Response(429, request=_REQUEST), body=None),
            "llm_error",
            id="throttled",
        ),
        pytest.param([_start(), _HANG], "timeout", id="job-timeout"),
    ],
)
async def test_bedrock_failures_fail_the_chapter_and_refund_the_premium_price(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    llm: _ModelLLM,
    enqueued: list[uuid.UUID],
    events: list[Any] | BaseException,
    code: str,
) -> None:
    """실제 Bedrock 클라이언트(SDK 경계만 가짜)를 라우팅 클라이언트 뒤에 두고 돌린다 — 공급자 예외가 실행 경로의 실패
    사유로 떨어지고, 상위 모델 가격 그대로 한 번 환불되는지 본다. Gemini 로 대신 쓰지 않는다."""
    monkeypatch.setattr(settings, "bedrock_access_key_id", "AKIATEST")
    monkeypatch.setattr(settings, "bedrock_secret_access_key", "secret-test")
    # 작업 상한은 멈춘 스트림(5초)에서만 걸려야 한다 — 입력 조립 중에 걸리면 취소가 테스트 커넥션을 끊는다.
    monkeypatch.setattr(settings, "novelize_job_timeout_seconds", 2)

    async def no_usage_recording(*_: Any) -> None:
        return None

    monkeypatch.setattr(bedrock_module, "record_usage", no_usage_recording)

    async def create(**_: Any) -> AsyncIterator[Any]:
        if isinstance(events, BaseException):
            raise events

        async def stream() -> AsyncIterator[Any]:
            for event in events:
                if event is _HANG:
                    await asyncio.sleep(5)
                yield event

        return stream()

    bedrock = BedrockLLMClient()
    monkeypatch.setattr(bedrock, "_client", SimpleNamespace(messages=SimpleNamespace(create=create)))
    client = RoutingLLMClient(_UnusedGemini(), factories={"bedrock": lambda: bedrock})
    room, novel_id, owner_id = await _novel(db_client, db_session, monkeypatch, premium=True)
    resp = await _create(db_client, novel_id, room, cost=105, model="sonnet")
    assert resp.status_code == 202, resp.text

    await runner.run_job(_factory(db_session), client, enqueued[0])

    (job,) = await _jobs(db_session, novel_id)
    assert (job.status, job.failure_code, job.refunded_at is not None) == ("failed", code, True)
    assert await _novel_ledger(db_session, owner_id) == [("novelize_spend", -105), ("novelize_refund", 105)]


async def test_a_job_whose_model_left_the_registry_fails_and_is_refunded_instead_of_running_on_gemini(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    llm: _ModelLLM,
    enqueued: list[uuid.UUID],
) -> None:
    """값을 낸 뒤 배포로 그 모델이 레지스트리에서 빠졌다 — 기본 모델로 대신 쓰면 그 값을 내고 다른 모델의 글을 받는다."""
    room, novel_id, owner_id = await _novel(db_client, db_session, monkeypatch, premium=True)
    resp = await _create(db_client, novel_id, room, cost=105, model="sonnet")
    assert resp.status_code == 202, resp.text
    await db_session.execute(sa.update(NovelJob).values(model="retired-model"))
    await db_session.commit()

    await runner.run_job(_factory(db_session), llm, enqueued[0])

    (job,) = await _jobs(db_session, novel_id)
    assert (job.status, job.failure_code) == ("failed", "internal")
    assert llm.calls == []
    assert await _novel_ledger(db_session, owner_id) == [("novelize_spend", -105), ("novelize_refund", 105)]


# ── 경계 제안·생성의 모델별 턴 상한 ─────────────────────────────────────────
def _per_model_turn_limits(monkeypatch: pytest.MonkeyPatch) -> None:
    """Gemini 는 3턴 방 전체(4턴)를 담고 Opus 는 2턴까지만 담게 한다."""
    monkeypatch.setattr(settings, "novelize_chapter_max_turns", 45)
    monkeypatch.setattr(settings, "novelize_chapter_max_turns_opus", 2)


async def test_an_opus_proposal_has_no_candidate_beyond_the_opus_turn_limit(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, llm: _ModelLLM
) -> None:
    """후보와 AI 제안이 요청한 모델의 턴 상한 안이다 — Gemini 상한으로 자르면 Opus 가 담지 못하는 끝을 고를 수 있다.
    후보마다 화 수·금액도 그 모델 기준이다(Opus 는 화 수 상한 1이라 늘 1화)."""
    room, novel_id, _ = await _novel(db_client, db_session, monkeypatch, premium=True)
    _per_model_turn_limits(monkeypatch)
    opening = (await _room_messages(db_session, room.room_id))[0]

    opus = await db_client.post(f"/novels/{novel_id}/chapter-proposal", json={"model": "opus"})
    gemini = await db_client.post(f"/novels/{novel_id}/chapter-proposal", json={"model": "gemini"})

    assert opus.status_code == 200, opus.text
    assert [(c["messageId"], c["episodeCount"], c["cost"]) for c in opus.json()["candidates"]] == [
        (str(opening.id), 1, 170),
        (str(room.turns[1][1].id), 1, 170),
    ]
    assert len(gemini.json()["candidates"]) == 4


async def test_an_opus_chapter_ending_beyond_the_opus_turn_limit_is_422(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    llm: _ModelLLM,
    enqueued: list[uuid.UUID],
) -> None:
    room, novel_id, owner_id = await _novel(db_client, db_session, monkeypatch, premium=True)
    _per_model_turn_limits(monkeypatch)
    end = {"endMessageId": str(room.turns[2][1].id)}

    opus = await db_client.post(f"/novels/{novel_id}/chapters", json={**end, "model": "opus", "expectedCost": 170})
    gemini = await db_client.post(f"/novels/{novel_id}/chapters", json={**end, "model": "gemini", "expectedCost": 40})

    assert opus.status_code == 422 and opus.json()["detail"] == {"code": "NOVEL_CHAPTER_END_INVALID"}
    assert gemini.status_code == 202, gemini.text
    assert await _novel_ledger(db_session, owner_id) == [("novelize_spend", -40)]


async def test_a_premium_proposal_without_novel_premium_access_is_403_before_the_model_or_the_limit(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, llm: _ModelLLM
) -> None:
    """허용 없는 계정의 상위 모델 제안은 경계 제안 모델을 부르지 않고, 시간당 제안 상한도 깎지 않는다."""
    monkeypatch.setattr(settings, "novelize_proposal_hourly_limit", 1)
    _, novel_id, _ = await _novel(db_client, db_session, monkeypatch, premium=False)

    denied = await db_client.post(f"/novels/{novel_id}/chapter-proposal", json={"model": "opus"})
    allowed = await db_client.post(f"/novels/{novel_id}/chapter-proposal", json={"model": "gemini"})

    assert denied.status_code == 403 and denied.json()["detail"] == {"code": "NOVEL_MODEL_NOT_ALLOWED"}
    assert allowed.status_code == 200, allowed.text
    assert llm.boundary_calls == 1


async def test_asking_again_with_another_model_counts_toward_the_hourly_proposal_limit(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, llm: _ModelLLM
) -> None:
    """모델을 바꿔 다시 받는 제안도 경계 제안 모델을 실제로 부르므로 같은 상한에 센다."""
    monkeypatch.setattr(settings, "novelize_proposal_hourly_limit", 2)
    _, novel_id, _ = await _novel(db_client, db_session, monkeypatch, premium=True)

    statuses = [
        (await db_client.post(f"/novels/{novel_id}/chapter-proposal", json={"model": model})).status_code
        for model in ("gemini", "opus", "sonnet")
    ]

    assert statuses == [200, 200, 429]
    assert llm.boundary_calls == 2
