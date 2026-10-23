"""소설 전체 구성안 라우트 — 요청(과금)·실행·리비전 저장·편집·승인. 구성 흐름 스위치가 꺼져 있으면 모두 404 다.

방은 `_novel_setup` 이 만든다(잔액 100). 메시지는 오프닝 하나 + `turns` 쌍이라 키 순 목록 `ms` 에서 `ms[0]` 이 오프닝(모델 응답),
`ms[2k-1]`·`ms[2k]` 가 k번째 사용자 말·응답이다. 기본 선택(`_SECTIONS`)은 include `ms[0..4]` · context `ms[5..6]` · 고르지 않은
`ms[7..8]`(exclude) · include `ms[9..12]` 이다 — include 턴은 앞 구간의 셋(오프닝, 1·2턴)과 뒤 구간의 둘(5·6턴)이라 모델이 보는 턴
번호는 1~5 다.

요청 라우트는 작업을 띄우는 함수를 기록용으로 바꿔 끼우고, 실행은 그 작업을 `runner.run_job` 에 가짜 모델로 넘겨 이어 본다."""

import uuid
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from typing import Any

import httpx
import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from api.core import clover
from api.core.config import settings
from api.db.models import ChatMessage, ChatRoom, Content, NovelJob
from api.db.models.novel import NovelOutline
from api.llm.client import LLMCallContext, LLMClient, LLMClientError, LLMPolicyViolationError, T
from api.novelize import router as novelize_router
from api.novelize import runner
from factories import (
    _add_chapter,
    _allow_novel_premium,
    _clear_llm_override,
    _make_user,
    _novel_ledger,
    _novel_setup,
    _override_llm_client,
    _room_messages,
)

pytestmark = pytest.mark.usefixtures("novel_prices_for_flow_tests")

_EXCLUDED = "빼기로-한-구간-표지"
_CONTEXT = "맥락으로만-보낸-구간-표지"
_INCLUDED = "소설에-넣은-구간-표지"
_SECTIONS = (("include", 0, 4), ("context", 5, 6), ("include", 9, 12))
_TWO_EPISODES = [
    {"title": "첫 만남", "summary": "둘이 처음 만났다.", "goal": "서로를 궁금해한다.", "start_turn": 1, "end_turn": 2},
    {"title": "다시 만남", "summary": "둘이 다시 만났다.", "goal": "약속을 남긴다.", "start_turn": 3, "end_turn": 5},
]


class _OutlineLLM(LLMClient):
    """전체 구성안 구조화 호출만 받는다. `episodes` 를 응답으로 돌려주거나 `error` 를 낸다. 받은 본문·지시문·사용 맥락·스키마를
    `calls` 에 적고, `on_call` 이 있으면 응답 전에 부른다(호출 도중 사용자가 무엇을 바꾸는 경합)."""

    def __init__(
        self,
        episodes: list[dict[str, Any]] | None = None,
        *,
        error: Exception | None = None,
        on_call: Callable[[], Awaitable[None]] | None = None,
    ) -> None:
        self.episodes = _TWO_EPISODES if episodes is None else episodes
        self.error = error
        self.on_call = on_call
        self.calls: list[tuple[str, str, LLMCallContext, Any]] = []

    async def generate(
        self,
        prompt: str,
        system_instruction: str | None = None,
        stop_sequences: list[str] | None = None,
        *,
        usage: LLMCallContext,
    ) -> AsyncIterator[str]:  # pragma: no cover - 불리면 시험 실패
        raise AssertionError("전체 구성안은 스트림 호출을 쓰지 않는다")
        yield ""

    async def generate_structured(
        self, prompt: str, response_schema: Any, images: Any = None, *, usage: LLMCallContext
    ) -> Any:  # pragma: no cover - 불리면 시험 실패
        raise AssertionError("전체 구성안은 지시문 없는 구조화 호출을 쓰지 않는다")

    async def generate_structured_with_instruction(
        self, prompt: str, response_schema: type[T], *, system_instruction: str, usage: LLMCallContext
    ) -> T:
        self.calls.append((prompt, system_instruction, usage, response_schema))
        if self.on_call is not None:
            await self.on_call()
        if self.error is not None:
            raise self.error
        return response_schema.model_validate({"episodes": self.episodes})


@pytest.fixture
def outline_flow_on(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setattr(settings, "novelize_outline_flow_enabled", True)
    yield


@pytest.fixture(autouse=True)
def _outline_prices(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(clover, "NOVELIZE_OUTLINE_COST", 11)
    monkeypatch.setattr(clover, "NOVELIZE_OUTLINE_COST_SONNET", 12)
    monkeypatch.setattr(clover, "NOVELIZE_OUTLINE_COST_OPUS", 13)


@pytest.fixture
def enqueued(monkeypatch: pytest.MonkeyPatch) -> list[uuid.UUID]:
    """라우트가 띄운 작업 id. 실제로 돌리지는 않는다 — 시험이 `_run` 으로 이어 돌린다."""
    seen: list[uuid.UUID] = []

    async def record(_factory: Any, _llm: Any, job_id: uuid.UUID) -> None:
        seen.append(job_id)

    monkeypatch.setattr(novelize_router, "enqueue_job", record)
    return seen


@pytest.fixture(autouse=True)
def llm() -> Iterator[_OutlineLLM]:
    """모든 시험에서 모델 클라이언트를 가짜로 갈아 끼운다 — 만들기 라우트는 본문 전에 클라이언트를 받으므로, 갈아 끼우지 않으면 키가
    없는 환경에서 거절 시험까지 클라이언트 생성에서 실패한다."""
    fake = _OutlineLLM()
    _override_llm_client(fake)
    yield fake
    _clear_llm_override()


def _factory(db_session: AsyncSession) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(bind=db_session.bind, expire_on_commit=False, join_transaction_mode="create_savepoint")


async def _run(db_session: AsyncSession, llm: LLMClient, job_id: uuid.UUID) -> NovelJob:
    await runner.run_job(_factory(db_session), llm, job_id)
    return await db_session.get_one(NovelJob, job_id, populate_existing=True)


def _code(response: httpx.Response) -> tuple[int, str]:
    return response.status_code, response.json()["detail"]["code"]


def _range(ms: list[ChatMessage], a: int, b: int) -> dict[str, str]:
    return {"startMessageId": str(ms[a].id), "endMessageId": str(ms[b].id)}


async def _rewrite(db: AsyncSession, message: ChatMessage, marker: str) -> None:
    await db.execute(
        sa.update(ChatMessage).where(ChatMessage.id == message.id).values(content=f"{message.content} {marker}")
    )
    await db.commit()


async def _select(
    db_client: httpx.AsyncClient, novel_id: uuid.UUID, ms: list[ChatMessage], sections: tuple[tuple[str, int, int], ...]
) -> None:
    """선택을 초안으로 저장하고 승인한다(가장 최근 리비전 위에)."""
    base = f"/novels/{novel_id}/source-selection"
    state = (await db_client.get(base)).json()
    latest = state["draft"] or state["approved"]
    shown = latest or state["proposal"]
    saved = await db_client.put(
        f"{base}/draft",
        json={
            "baseRevision": None if latest is None else latest["revision"],
            "extendToRoomEnd": False,
            "roomEndMessageId": shown["roomEndMessageId"],
            "sections": [
                {"mode": mode, "startMessageId": str(ms[a].id), "endMessageId": str(ms[b].id)} for mode, a, b in sections
            ],
        },
    )
    assert saved.status_code == 200, saved.text
    approved = await db_client.post(f"{base}/approve", json={"revision": saved.json()["draft"]["revision"]})
    assert approved.status_code == 200, approved.text


async def _ready(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    *,
    persona: str | None = "서진",
) -> tuple[uuid.UUID, uuid.UUID, list[ChatMessage]]:
    """6턴 방의 소설에 기본 선택을 승인해 둔다. (방 id, 소설 id, 키 순 메시지)."""
    room, novel_id = await _novel_setup(db_client, db_session, monkeypatch, turns=6, persona=persona)
    ms = await _room_messages(db_session, room.room_id)
    await _select(db_client, novel_id, ms, _SECTIONS)
    return room.room_id, novel_id, ms


async def _request(
    db_client: httpx.AsyncClient, novel_id: uuid.UUID, *, model: str = "gemini", cost: int = 11
) -> httpx.Response:
    return await db_client.post(f"/novels/{novel_id}/outline", json={"model": model, "expectedCost": cost})


async def _outlines(db: AsyncSession, novel_id: uuid.UUID) -> list[NovelOutline]:
    rows = await db.scalars(
        sa.select(NovelOutline)
        .where(NovelOutline.novel_id == novel_id)
        .order_by(NovelOutline.revision)
        .execution_options(populate_existing=True)
    )
    return list(rows.all())


async def _generated(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    enqueued: list[uuid.UUID],
    llm: _OutlineLLM,
) -> tuple[uuid.UUID, list[ChatMessage], dict[str, Any]]:
    """기본 선택으로 구성안을 하나 만들어 둔다. (소설 id, 메시지, 조회 상태)."""
    _, novel_id, ms = await _ready(db_client, db_session, monkeypatch)
    response = await _request(db_client, novel_id)
    assert response.status_code == 202, response.text
    job = await _run(db_session, llm, enqueued[-1])
    assert job.status == "succeeded", job.failure_code
    state = (await db_client.get(f"/novels/{novel_id}/outline")).json()
    return novel_id, ms, state


def _episode_input(episode: dict[str, Any], **changes: Any) -> dict[str, Any]:
    body = {k: episode[k] for k in ("key", "title", "summary", "goal", "basis")}
    body.update(changes)
    return body


async def _save(
    db_client: httpx.AsyncClient, novel_id: uuid.UUID, base: int, episodes: list[dict[str, Any]]
) -> httpx.Response:
    return await db_client.put(f"/novels/{novel_id}/outline/draft", json={"baseRevision": base, "episodes": episodes})


async def _approve(db_client: httpx.AsyncClient, novel_id: uuid.UUID, revision: int) -> httpx.Response:
    return await db_client.post(f"/novels/{novel_id}/outline/approve", json={"revision": revision})


# ── 스위치 ──────────────────────────────────────────────────────────────────
async def test_every_outline_route_is_a_no_store_404_while_the_flow_switch_is_off(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, enqueued: list[uuid.UUID]
) -> None:
    """스위치가 꺼져 있으면 조회·요청·저장·승인이 모두 404 `NOVEL_OUTLINE_FLOW_DISABLED`(캐시 안 함)이고 차감도 작업도 없다.
    깨지는 시나리오: 꺼 둔 운영에서 구성안 값을 받거나, 브라우저가 404 를 붙잡아 켠 뒤에도 화면이 열리지 않는다."""
    room, novel_id = await _novel_setup(db_client, db_session, monkeypatch, turns=2)
    base = f"/novels/{novel_id}/outline"

    responses = [
        await db_client.get(base),
        await db_client.post(base, json={"model": "gemini", "expectedCost": 11}),
        await db_client.put(f"{base}/draft", json={"baseRevision": 1, "episodes": []}),
        await db_client.post(f"{base}/approve", json={"revision": 1}),
    ]

    assert [_code(r) for r in responses] == [(404, "NOVEL_OUTLINE_FLOW_DISABLED")] * 4
    assert {r.headers.get("cache-control") for r in responses} == {"no-store"}
    assert enqueued == []
    assert await _novel_ledger(db_session, room.user_id) == []


# ── 요청 거절(차감 전) ──────────────────────────────────────────────────────
@pytest.mark.usefixtures("outline_flow_on")
async def test_an_outline_needs_an_approved_selection(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, enqueued: list[uuid.UUID]
) -> None:
    """승인한 구간 선택이 없으면 409 `NOVEL_SOURCE_SELECTION_REQUIRED` 이고 원장에 아무것도 남지 않는다. 깨지는 시나리오: 선택
    없이 방 전체를 읽어(사용자가 빼려던 대화까지) 구성안을 판다."""
    room, novel_id = await _novel_setup(db_client, db_session, monkeypatch, turns=2)

    response = await _request(db_client, novel_id)

    assert _code(response) == (409, "NOVEL_SOURCE_SELECTION_REQUIRED")
    assert enqueued == []
    assert await _novel_ledger(db_session, room.user_id) == []


@pytest.mark.usefixtures("outline_flow_on")
async def test_an_oversized_selection_is_refused_before_charging_with_a_reduce_sections_code(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, enqueued: list[uuid.UUID]
) -> None:
    """고른 원문의 입력 견적이 상한을 넘으면 모델을 부르기 전·차감 전에 422 `NOVEL_OUTLINE_INPUT_TOO_LARGE` 이고, 견적과 상한을
    함께 싣는다(화면이 "구간을 줄여 주세요"를 띄운다). 맥락 구간도 입력이라 견적에 든다 — 맥락을 뺀 선택은 견적이 줄고, 그 견적이
    상한 안이면 받아진다. 깨지는 시나리오: 넘는 입력을 조용히
    잘라 보내거나, 호출이 실패한 뒤에야 알려 원가만 나간다."""
    room_id, novel_id, ms = await _ready(db_client, db_session, monkeypatch)
    monkeypatch.setattr(settings, "novelize_outline_max_input_tokens", 10)

    refused = await _request(db_client, novel_id)

    assert _code(refused) == (422, "NOVEL_OUTLINE_INPUT_TOO_LARGE")
    detail = refused.json()["detail"]
    assert detail["maxInputTokens"] == 10
    assert detail["estimatedInputTokens"] > 10
    assert enqueued == []
    user_id = await db_session.scalar(sa.select(ChatRoom.user_id).where(ChatRoom.id == room_id))
    assert user_id is not None
    assert await _novel_ledger(db_session, user_id) == []

    await _select(db_client, novel_id, ms, (_SECTIONS[0], _SECTIONS[2]))
    without_context = (await _request(db_client, novel_id)).json()["detail"]["estimatedInputTokens"]
    assert without_context < detail["estimatedInputTokens"]

    monkeypatch.setattr(settings, "novelize_outline_max_input_tokens", without_context)
    assert (await _request(db_client, novel_id)).status_code == 202


@pytest.mark.usefixtures("outline_flow_on")
async def test_an_unlocked_novel_of_a_work_that_forbids_novelizing_is_refused_before_charging(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, enqueued: list[uuid.UUID]
) -> None:
    """아직 첫 화가 없는(잠기지 않은) 소설은 원작의 지금 허락을 다시 본다 — 다른 작가가 소설화를 막았으면 403
    `CONTENT_NOVELIZE_FORBIDDEN` 이고 차감하지 않는다. 깨지는 시나리오: 허락을 거둔 원작으로 구성안 값을 받는다."""
    room_id, novel_id, _ = await _ready(db_client, db_session, monkeypatch)
    content_id = await db_session.scalar(sa.select(ChatRoom.content_id).where(ChatRoom.id == room_id))
    creator = _make_user()
    db_session.add(creator)
    await db_session.flush()
    await db_session.execute(
        sa.update(Content).where(Content.id == content_id).values(novel_permission="forbidden", creator_user_id=creator.id)
    )
    await db_session.commit()

    response = await _request(db_client, novel_id)

    assert _code(response) == (403, "CONTENT_NOVELIZE_FORBIDDEN")
    assert enqueued == []
    owner = await db_session.scalar(sa.select(ChatRoom.user_id).where(ChatRoom.id == room_id))
    assert owner is not None
    assert await _novel_ledger(db_session, owner) == []


@pytest.mark.usefixtures("outline_flow_on")
async def test_a_changed_selected_source_is_refused_before_charging(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, enqueued: list[uuid.UUID]
) -> None:
    """승인 뒤 고른 구간의 원문이 바뀌었으면 409 `NOVEL_SOURCE_SELECTION_SOURCE_CHANGED`(다시 골라 승인한다)이고 차감하지
    않는다. 빼기로 한 사이의 원문이 바뀐 것은 막지 않는다. 깨지는 시나리오: 사용자가 승인한 것과 다른 원문으로 구성안을 판다."""
    _, novel_id, ms = await _ready(db_client, db_session, monkeypatch)
    await _rewrite(db_session, ms[7], _EXCLUDED)
    assert (await _request(db_client, novel_id)).status_code == 202
    await db_session.execute(sa.update(NovelJob).where(NovelJob.novel_id == novel_id).values(status="failed"))
    await db_session.commit()

    await _rewrite(db_session, ms[9], "고친 글")
    response = await _request(db_client, novel_id)

    assert _code(response) == (409, "NOVEL_SOURCE_SELECTION_SOURCE_CHANGED")
    assert len(enqueued) == 1


@pytest.mark.usefixtures("outline_flow_on")
async def test_a_selected_include_section_written_into_a_chapter_after_approval_is_refused(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, enqueued: list[uuid.UUID]
) -> None:
    """승인 뒤 include 구간이 화가 되었으면(옛 흐름으로 이어 쓴 경우) 422 `NOVEL_SOURCE_SECTION_LOCKED` 이고 차감하지 않는다.
    깨지는 시나리오: 이미 화가 된 대화로 구성안을 짜 같은 장면을 두 번 산다."""
    room, novel_id = await _novel_setup(db_client, db_session, monkeypatch, turns=6)
    ms = await _room_messages(db_session, room.room_id)
    await _select(db_client, novel_id, ms, _SECTIONS)
    await _add_chapter(db_session, novel_id, room, ms[0], ms[2])

    response = await _request(db_client, novel_id)

    assert _code(response) == (422, "NOVEL_SOURCE_SECTION_LOCKED")
    assert enqueued == []
    assert await _novel_ledger(db_session, room.user_id) == []


@pytest.mark.usefixtures("outline_flow_on")
async def test_an_outline_needs_the_protagonist_name_before_charging(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, enqueued: list[uuid.UUID]
) -> None:
    """주인공 이름이 비면 422 `NOVEL_PROTAGONIST_NAME_REQUIRED` 이고 차감하지 않는다. 깨지는 시나리오: 이름 칸이 빈 프롬프트로
    값을 받은 뒤 렌더 실패로 환불만 남는다."""
    room_id, novel_id, _ = await _ready(db_client, db_session, monkeypatch, persona=None)

    response = await _request(db_client, novel_id)

    assert _code(response) == (422, "NOVEL_PROTAGONIST_NAME_REQUIRED")
    assert enqueued == []
    owner = await db_session.scalar(sa.select(ChatRoom.user_id).where(ChatRoom.id == room_id))
    assert owner is not None
    assert await _novel_ledger(db_session, owner) == []


# ── 요청·실행 ───────────────────────────────────────────────────────────────
@pytest.mark.usefixtures("outline_flow_on")
async def test_an_outline_is_charged_once_run_on_the_gateway_and_stored_as_an_unapproved_revision(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    enqueued: list[uuid.UUID],
    llm: _OutlineLLM,
) -> None:
    """요청은 202 로 진행 대기 작업을 넣고 모델별 고정가를 한 번 깎는다. 실행은 전체 구성안 호출 위치로 고른 모델을 실어 부르고,
    모델이 턴 번호로 밝힌 화 근거를 메시지 구간으로 바꿔 미승인 리비전 1(출처 generate)로 남긴다. 화 근거는 include 구간을 넘지
    않는다 — 두 include 구간에 걸친 화는 구간마다 따로 적힌다. 깨지는 시나리오: 근거가 사이의 빼기로 한 대화를 덮어 이어 쓰기에
    새거나, 구성안이 곧바로 승인돼 사용자가 고칠 틈이 없다."""
    room_id, novel_id, ms = await _ready(db_client, db_session, monkeypatch)
    owner = await db_session.scalar(sa.select(ChatRoom.user_id).where(ChatRoom.id == room_id))
    assert owner is not None

    response = await _request(db_client, novel_id)

    assert response.status_code == 202, response.text
    body = response.json()
    assert (body["kind"], body["status"], body["chargedAmount"], body["model"]) == (
        "outline_generate",
        "queued",
        11,
        "gemini",
    )
    job = await _run(db_session, llm, enqueued[-1])

    assert (job.status, job.failure_code) == ("succeeded", None)
    ((_, _, usage, _),) = llm.calls
    assert (usage.call_site, usage.model, usage.user_id, usage.room_id) == ("novelize_outline", "gemini", owner, room_id)
    (outline,) = await _outlines(db_session, novel_id)
    assert (outline.revision, outline.source, outline.approved_at, outline.job_id, outline.model) == (
        1,
        "generate",
        None,
        job.id,
        "gemini",
    )
    state = (await db_client.get(f"/novels/{novel_id}/outline")).json()
    assert state["approved"] is None
    draft = state["draft"]
    assert (draft["revision"], draft["source"], draft["stale"]) == (1, "generate", False)
    assert [(e["title"], e["summary"], e["goal"]) for e in draft["episodes"]] == [
        ("첫 만남", "둘이 처음 만났다.", "서로를 궁금해한다."),
        ("다시 만남", "둘이 다시 만났다.", "약속을 남긴다."),
    ]
    assert [e["basis"] for e in draft["episodes"]] == [
        [_range(ms, 0, 2)],
        [_range(ms, 3, 4), _range(ms, 9, 12)],
    ]
    assert len({e["key"] for e in draft["episodes"]}) == 2
    assert await _novel_ledger(db_session, owner) == [("novelize_spend", -11)]


@pytest.mark.usefixtures("outline_flow_on")
async def test_the_excluded_gap_never_reaches_the_model_and_context_stays_out_of_the_turn_lines(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    enqueued: list[uuid.UUID],
    llm: _OutlineLLM,
) -> None:
    """빼기로 한 사이(`ms[7..8]`)에 심은 표지는 모델이 받은 지시문·본문 어디에도 없다(0회). 맥락 구간의 표지는 본문에 있지만
    번호 붙은 원문 줄(`[턴 n]`)에는 없고, include 표지는 원문 줄에 있다. 깨지는 시나리오: 구간 사이를 이어 읽어 사용자가 뺀 대화가
    모델에 가거나, 맥락으로만 보낸 대화가 화의 근거 턴으로 섞인다."""
    _, novel_id, ms = await _ready(db_client, db_session, monkeypatch)
    for message in (ms[7], ms[8]):
        await _rewrite(db_session, message, _EXCLUDED)
    await _rewrite(db_session, ms[5], _CONTEXT)
    await _rewrite(db_session, ms[10], _INCLUDED)
    await _select(db_client, novel_id, await _room_messages(db_session, ms[0].chat_room_id), _SECTIONS)

    assert (await _request(db_client, novel_id)).status_code == 202
    assert (await _run(db_session, llm, enqueued[-1])).status == "succeeded"

    ((prompt, system_instruction, _, _),) = llm.calls
    assert (prompt + system_instruction).count(_EXCLUDED) == 0
    turn_lines = [line for line in prompt.splitlines() if line.startswith("[턴 ")]
    assert prompt.count(_CONTEXT) == 1
    assert not any(_CONTEXT in line for line in turn_lines)
    assert [line.split("]")[0] for line in turn_lines if _INCLUDED in line] == ["[턴 4"]
    assert max(int(line.split("]")[0].removeprefix("[턴 ")) for line in turn_lines) == 5


@pytest.mark.usefixtures("outline_flow_on")
async def test_a_premium_outline_carries_the_chosen_model_and_its_price(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    enqueued: list[uuid.UUID],
    llm: _OutlineLLM,
) -> None:
    """상위 모델은 허용이 있어야 하고(없으면 403 `NOVEL_MODEL_NOT_ALLOWED`, 차감 없음), 허용되면 그 모델의 구성안 가격을 깎고
    실행은 그 모델을 실어 부른다. 깨지는 시나리오: Sonnet 값을 받고 Gemini 로 부르거나, 허용 없는 계정이 상위 모델을 산다."""
    room_id, novel_id, _ = await _ready(db_client, db_session, monkeypatch)
    owner = await db_session.scalar(sa.select(ChatRoom.user_id).where(ChatRoom.id == room_id))
    assert owner is not None

    assert _code(await _request(db_client, novel_id, model="sonnet", cost=12)) == (403, "NOVEL_MODEL_NOT_ALLOWED")
    await _allow_novel_premium(db_session, monkeypatch, owner)
    state = (await db_client.get(f"/novels/{novel_id}/outline")).json()
    assert {m["id"]: m["cost"] for m in state["models"]} == {"gemini": 11, "sonnet": 12, "opus": 13}
    assert _code(await _request(db_client, novel_id, model="sonnet", cost=11)) == (409, "NOVELIZE_PRICE_CHANGED")
    response = await _request(db_client, novel_id, model="sonnet", cost=12)
    assert response.status_code == 202, response.text
    await _run(db_session, llm, enqueued[-1])

    ((_, _, usage, _),) = llm.calls
    assert (usage.call_site, usage.model) == ("novelize_outline", "sonnet")
    assert (await _outlines(db_session, novel_id))[0].model == "sonnet"
    assert await _novel_ledger(db_session, owner) == [("novelize_spend", -12)]


@pytest.mark.usefixtures("outline_flow_on")
async def test_a_second_request_while_one_runs_is_refused_without_a_second_charge(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    enqueued: list[uuid.UUID],
    committing_request_session: None,
) -> None:
    """두 번 눌러도 작업 하나·차감 하나다 — 두 번째는 409 `NOVEL_JOB_IN_PROGRESS`. 요청마다 커밋이 진짜 경계인 세션으로 돌린다(거절한
    요청의 되감기가 앞 요청의 차감까지 지우지 않게). 깨지는 시나리오: 연타가 구성안 값을 두 번 깎는다."""
    room_id, novel_id, _ = await _ready(db_client, db_session, monkeypatch)
    owner = await db_session.scalar(sa.select(ChatRoom.user_id).where(ChatRoom.id == room_id))
    assert owner is not None

    first = await _request(db_client, novel_id)
    second = await _request(db_client, novel_id)

    assert first.status_code == 202
    assert _code(second) == (409, "NOVEL_JOB_IN_PROGRESS")
    assert len(enqueued) == 1
    assert await _novel_ledger(db_session, owner) == [("novelize_spend", -11)]


_BAD_EPISODES = {
    "none": [],
    "turn_after_the_last": [{**_TWO_EPISODES[0], "start_turn": 1, "end_turn": 6}],
    "turn_zero": [{**_TWO_EPISODES[0], "start_turn": 0, "end_turn": 2}],
    "reversed_turns": [{**_TWO_EPISODES[0], "start_turn": 3, "end_turn": 2}],
    "overlapping": [_TWO_EPISODES[0], {**_TWO_EPISODES[1], "start_turn": 2}],
    "out_of_order": [_TWO_EPISODES[1], _TWO_EPISODES[0]],
    "blank_title": [{**_TWO_EPISODES[0], "title": "  "}, _TWO_EPISODES[1]],
}


@pytest.mark.usefixtures("outline_flow_on")
@pytest.mark.parametrize(
    ("llm_case", "failure"),
    [
        pytest.param({"error": LLMClientError("boom")}, "llm_error", id="llm_error"),
        pytest.param({"error": LLMPolicyViolationError("no")}, "blocked", id="refused_by_policy"),
        pytest.param(
            {"episodes": [{**_TWO_EPISODES[0], "summary": "죄송합니다. 이 대화로는 구성안을 만들 수 없습니다."}]},
            "refused",
            id="refusal_text",
        ),
        *(pytest.param({"episodes": bad}, "malformed", id=name) for name, bad in _BAD_EPISODES.items()),
    ],
)
async def test_a_failed_or_refused_outline_is_refunded_once_and_stores_nothing(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    enqueued: list[uuid.UUID],
    llm_case: dict[str, Any],
    failure: str,
) -> None:
    """모델 오류·정책 거절·거절문 줄거리, 그리고 화가 없거나 턴 번호가 범위·순서를 벗어난 구성안은 실패로 끝나 전액을 한 번 돌려주고(원장 짝 1)
    구성안 행을 남기지 않는다. 깨지는 시나리오: 쓸 수 없는 구성안에 값을 받거나, 빈 화·겹친 화가 승인 대상으로 남는다."""
    room_id, novel_id, _ = await _ready(db_client, db_session, monkeypatch)
    owner = await db_session.scalar(sa.select(ChatRoom.user_id).where(ChatRoom.id == room_id))
    assert owner is not None
    assert (await _request(db_client, novel_id)).status_code == 202

    job = await _run(db_session, _OutlineLLM(**llm_case), enqueued[-1])

    assert (job.status, job.failure_code, job.refunded_amount) == ("failed", failure, 11)
    assert await _outlines(db_session, novel_id) == []
    assert await _novel_ledger(db_session, owner) == [("novelize_spend", -11), ("novelize_refund", 11)]


@pytest.mark.usefixtures("outline_flow_on")
async def test_more_episodes_than_the_cap_is_a_refunded_failure(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, enqueued: list[uuid.UUID]
) -> None:
    """화 수 상한을 넘는 구성안은 `malformed` 실패·환불이다(상한 1 에 화 둘). 깨지는 시나리오: 상한 밖 화 수를 받아 원고 단계에서
    값을 계속 받는다."""
    _, novel_id, _ = await _ready(db_client, db_session, monkeypatch)
    monkeypatch.setattr(settings, "novelize_outline_max_episodes", 1)
    assert (await _request(db_client, novel_id)).status_code == 202

    job = await _run(db_session, _OutlineLLM(), enqueued[-1])

    assert (job.status, job.failure_code) == ("failed", "malformed")
    assert await _outlines(db_session, novel_id) == []


@pytest.mark.usefixtures("outline_flow_on")
async def test_a_source_change_between_request_and_run_is_a_refunded_failure(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, enqueued: list[uuid.UUID]
) -> None:
    """요청 뒤 실행 전에 고른 구간의 원문이 바뀌면 실행이 `source_changed` 실패·전액 환불이고 모델을 부르지 않는다. 깨지는
    시나리오: 승인한 것과 다른 원문으로 구성안을 짜 값을 받는다."""
    _, novel_id, ms = await _ready(db_client, db_session, monkeypatch)
    assert (await _request(db_client, novel_id)).status_code == 202
    await _rewrite(db_session, ms[10], "고친 글")
    fake = _OutlineLLM()

    job = await _run(db_session, fake, enqueued[-1])

    assert (job.status, job.failure_code, job.refunded_amount) == ("failed", "source_changed", 11)
    assert fake.calls == []


@pytest.mark.usefixtures("outline_flow_on")
async def test_a_selection_that_drops_a_basis_section_during_the_call_fails_the_outline_with_a_refund(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, enqueued: list[uuid.UUID]
) -> None:
    """모델을 부르는 동안 사용자가 근거 구간 하나를 뺀 선택을 승인하면, 그 구성안은 지금 선택에 없는 대화를 근거로 삼으므로 저장하지
    않고 `source_changed` 실패·환불이다. 깨지는 시나리오: 사용자가 뺀 대화를 근거로 한 구성안이 승인 대상으로 남는다."""
    _, novel_id, ms = await _ready(db_client, db_session, monkeypatch)
    assert (await _request(db_client, novel_id)).status_code == 202

    async def drop_last_section() -> None:
        await _select(db_client, novel_id, ms, (("include", 0, 4), ("context", 5, 6)))

    job = await _run(db_session, _OutlineLLM(on_call=drop_last_section), enqueued[-1])

    assert (job.status, job.failure_code, job.refunded_amount) == ("failed", "source_changed", 11)
    assert await _outlines(db_session, novel_id) == []


@pytest.mark.usefixtures("outline_flow_on")
async def test_a_selection_that_only_adds_a_section_during_the_call_keeps_the_outline(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, enqueued: list[uuid.UUID]
) -> None:
    """근거 구간을 그대로 둔 채 구간을 더한 선택을 승인한 것은 구성안을 낡게 하지 않는다 — 저장되고 낡음 표시도 없다. 깨지는
    시나리오: "새 대화 추가"만으로 값을 낸 구성안을 버리게 한다."""
    _, novel_id, ms = await _ready(db_client, db_session, monkeypatch)
    assert (await _request(db_client, novel_id)).status_code == 202

    async def add_a_section() -> None:
        await _select(db_client, novel_id, ms, (*_SECTIONS[:2], ("context", 7, 8), _SECTIONS[2]))

    job = await _run(db_session, _OutlineLLM(on_call=add_a_section), enqueued[-1])

    assert job.status == "succeeded"
    state = (await db_client.get(f"/novels/{novel_id}/outline")).json()
    assert (state["draft"]["revision"], state["draft"]["stale"]) == (1, False)


def test_the_episode_hint_is_the_source_length_formula_without_the_batch_cap_and_within_the_outline_cap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """화 수 안내값은 원문 분량 산식(글자 × 비율 ÷ 화 목표 길이, 반올림)을 그대로 쓰되 묶음 하나의 화 수 상한(Gemini 3)으로 자르지
    않고, 1 이상 구성안 화 수 상한 이하로만 자른다. 깨지는 시나리오: 방 전체 구성안의 안내가 묶음 상한 3화에 묶여 긴 방을 3화로
    뭉치라고 지시한다."""
    from api.novelize.outline import episode_hint

    monkeypatch.setattr(settings, "novelize_source_ratio", 0.8)
    monkeypatch.setattr(settings, "novelize_episode_target_chars", 5000)
    monkeypatch.setattr(settings, "novelize_outline_max_episodes", 30)

    assert [episode_hint(chars) for chars in (0, 3_000, 50_000, 1_000_000)] == [1, 1, 8, 30]


@pytest.mark.usefixtures("outline_flow_on")
async def test_an_outline_whose_include_text_changed_and_was_reselected_is_stale(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    enqueued: list[uuid.UUID],
    llm: _OutlineLLM,
) -> None:
    """같은 양 끝의 include 구간이라도 원문이 바뀐 뒤 다시 골라 승인했으면(해시가 다르면) 그 구간으로 만든 구성안은 낡았다. 깨지는
    시나리오: 바뀐 대화를 본 적 없는 구성안이 승인돼 다음 단계가 옛 줄거리로 새 원문을 쓴다."""
    novel_id, ms, _ = await _generated(db_client, db_session, monkeypatch, enqueued, llm)
    await _rewrite(db_session, ms[10], "고친 글")

    await _select(db_client, novel_id, await _room_messages(db_session, ms[0].chat_room_id), _SECTIONS)

    assert (await db_client.get(f"/novels/{novel_id}/outline")).json()["draft"]["stale"] is True
    assert _code(await _approve(db_client, novel_id, 1)) == (409, "NOVEL_OUTLINE_STALE")


# ── 편집·승인 ───────────────────────────────────────────────────────────────
@pytest.mark.usefixtures("outline_flow_on")
async def test_editing_an_approved_outline_makes_a_new_revision_and_leaves_the_approved_one_as_it_was(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    enqueued: list[uuid.UUID],
    llm: _OutlineLLM,
) -> None:
    """승인한 판을 고치면(화 나누기·순서·줄거리) 그 위의 새 미승인 리비전(출처 edit)이 되고, 승인한 판은 그대로 승인본으로 남는다.
    나눈 화는 새 화 키를, 남은 화는 원래 키를 갖는다. 새 판을 승인하면 승인본이 바뀐다. 무과금이다. 깨지는 시나리오: 승인본을
    제자리에서 고쳐 그 판을 근거로 산 다음 단계가 바뀐 줄 모르거나, 편집이 화 키를 새로 매겨 같은 화의 이력이 끊긴다."""
    novel_id, ms, state = await _generated(db_client, db_session, monkeypatch, enqueued, llm)
    first, second = state["draft"]["episodes"]
    assert (await _approve(db_client, novel_id, 1)).status_code == 200

    edited = [
        _episode_input(second, basis=[_range(ms, 9, 12)], summary="고친 줄거리"),
        _episode_input(first),
        _episode_input(second, key=None, title="나눈 화", basis=[_range(ms, 3, 4)]),
    ]
    saved = await _save(db_client, novel_id, 1, edited)

    assert saved.status_code == 200, saved.text
    body = saved.json()
    assert body["approved"]["revision"] == 1
    assert [e["key"] for e in body["approved"]["episodes"]] == [first["key"], second["key"]]
    draft = body["draft"]
    assert (draft["revision"], draft["source"], draft["approvedAt"], draft["model"]) == (2, "edit", None, None)
    keys = [e["key"] for e in draft["episodes"]]
    assert keys[:2] == [second["key"], first["key"]]
    assert keys[2] not in (first["key"], second["key"])
    assert draft["episodes"][0]["summary"] == "고친 줄거리"

    approved = await _approve(db_client, novel_id, 2)

    assert approved.status_code == 200, approved.text
    assert (approved.json()["approved"]["revision"], approved.json()["draft"]) == (2, None)
    rows = await _outlines(db_session, novel_id)
    assert [(r.revision, r.approved_at is not None) for r in rows] == [(1, True), (2, True)]


@pytest.mark.usefixtures("outline_flow_on")
async def test_an_edit_on_a_stale_base_revision_is_a_conflict(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    enqueued: list[uuid.UUID],
    llm: _OutlineLLM,
) -> None:
    """다른 탭이 먼저 새 리비전을 저장했으면 낡은 기준 리비전의 저장·승인은 409 `NOVEL_OUTLINE_CONFLICT` 다. 깨지는 시나리오: 늦은
    탭이 앞 탭의 편집을 조용히 덮거나, 사용자가 본 적 없는 판을 승인한다."""
    novel_id, _, state = await _generated(db_client, db_session, monkeypatch, enqueued, llm)
    episodes = [_episode_input(e) for e in state["draft"]["episodes"]]
    assert (await _save(db_client, novel_id, 1, episodes)).status_code == 200

    assert _code(await _save(db_client, novel_id, 1, episodes)) == (409, "NOVEL_OUTLINE_CONFLICT")
    assert _code(await _approve(db_client, novel_id, 1)) == (409, "NOVEL_OUTLINE_CONFLICT")
    assert [r.revision for r in await _outlines(db_session, novel_id)] == [1, 2]


@pytest.mark.usefixtures("outline_flow_on")
@pytest.mark.parametrize(
    "case",
    ["excluded_gap", "context_section", "overlapping_episodes", "unknown_key", "repeated_key", "no_reply", "split_turn", "over_cap"],
)
async def test_an_edit_whose_basis_leaves_the_included_turns_is_refused(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    enqueued: list[uuid.UUID],
    llm: _OutlineLLM,
    case: str,
) -> None:
    """편집한 화 근거는 그 구성안이 쓴 선택의 include 구간 안이어야 하고, 화끼리 겹치지 않으며, 화마다 모델 응답이 하나 이상
    있어야 한다 — 근거는 턴 경계에서 시작해 모델 응답으로 끝나므로 한 턴을 두 화에 메시지 단위로 나눌 수 없다. 화 키는 기준
    리비전의 것이거나 새 화(null)이고 겹치지 않는다. 화 수는 상한 안이다. 어기면 422
    `NOVEL_OUTLINE_INVALID` 이고 리비전이 생기지 않는다. 깨지는 시나리오: 편집으로 빼기로 한 대화·맥락 구간을 화 근거에 넣어 다음
    단계가 그 원문을 모델에 보내거나, 같은 턴이 두 화에 들어가 두 번 쓰이거나, 나뉜 턴의 사용자 말이 다음 단계에서 버려진다."""
    novel_id, ms, state = await _generated(db_client, db_session, monkeypatch, enqueued, llm)
    first, second = state["draft"]["episodes"]
    episodes = {
        "excluded_gap": [_episode_input(first), _episode_input(second, basis=[_range(ms, 3, 4), _range(ms, 7, 8)])],
        "context_section": [_episode_input(first, basis=[_range(ms, 0, 2), _range(ms, 5, 6)]), _episode_input(second)],
        "overlapping_episodes": [_episode_input(first, basis=[_range(ms, 0, 4)]), _episode_input(second)],
        "unknown_key": [_episode_input(first, key=str(uuid.uuid4())), _episode_input(second)],
        "repeated_key": [_episode_input(first), _episode_input(second, key=first["key"])],
        "no_reply": [_episode_input(first, basis=[_range(ms, 1, 1)]), _episode_input(second)],
        "split_turn": [
            _episode_input(first, basis=[_range(ms, 0, 1)]),
            _episode_input(second, basis=[_range(ms, 2, 4), _range(ms, 9, 12)]),
        ],
        "over_cap": [_episode_input(first), _episode_input(second)],
    }[case]
    if case == "over_cap":
        monkeypatch.setattr(settings, "novelize_outline_max_episodes", 1)

    response = await _save(db_client, novel_id, 1, episodes)

    assert _code(response) == (422, "NOVEL_OUTLINE_INVALID")
    assert response.json()["detail"]["reason"] == {
        "excluded_gap": "basis_outside_include",
        "context_section": "basis_outside_include",
        "overlapping_episodes": "basis_overlap",
        "unknown_key": "unknown_key",
        "repeated_key": "unknown_key",
        "no_reply": "basis_splits_turn",
        "split_turn": "basis_splits_turn",
        "over_cap": "too_many_episodes",
    }[case]
    assert [r.revision for r in await _outlines(db_session, novel_id)] == [1]


@pytest.mark.usefixtures("outline_flow_on")
async def test_an_outline_whose_basis_section_left_the_selection_is_stale_and_cannot_be_approved_or_edited(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    enqueued: list[uuid.UUID],
    llm: _OutlineLLM,
) -> None:
    """구성안이 근거로 쓴 include 구간이 지금 승인한 선택에 같은 양 끝·include·해시로 다 있으면 낡지 않았다(구간을 더하거나 맥락
    구간을 뺀 선택). include 구간이 하나라도 빠지면(빼거나 맥락으로 바꾼 선택) 낡았고, 낡은 구성안의 승인·편집은 409
    `NOVEL_OUTLINE_STALE` 이다. 깨지는 시나리오: 사용자가 뺀 대화를 근거로 한 구성안을 승인해 다음 단계가 그 대화를 모델에 보낸다."""
    novel_id, ms, state = await _generated(db_client, db_session, monkeypatch, enqueued, llm)
    episodes = [_episode_input(e) for e in state["draft"]["episodes"]]

    await _select(db_client, novel_id, ms, (*_SECTIONS[:2], ("context", 7, 8), _SECTIONS[2]))
    assert (await db_client.get(f"/novels/{novel_id}/outline")).json()["draft"]["stale"] is False
    await _select(db_client, novel_id, ms, (("include", 0, 4), ("include", 9, 12)))
    assert (await db_client.get(f"/novels/{novel_id}/outline")).json()["draft"]["stale"] is False

    await _select(db_client, novel_id, ms, (("include", 0, 4), ("context", 9, 12)))
    after = (await db_client.get(f"/novels/{novel_id}/outline")).json()

    assert after["draft"]["stale"] is True
    assert _code(await _approve(db_client, novel_id, 1)) == (409, "NOVEL_OUTLINE_STALE")
    assert _code(await _save(db_client, novel_id, 1, episodes)) == (409, "NOVEL_OUTLINE_STALE")


@pytest.mark.usefixtures("outline_flow_on")
async def test_the_outline_state_without_an_outline_lists_prices_and_the_cap(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """구성안이 없으면 승인본·초안이 비고, 고를 수 있는 모델과 그 구성안 가격, 화 수 상한을 싣는다(상위 모델 허용이 없으면 기본
    모델만). 저장·승인할 구성안이 없으면 409 `NOVEL_OUTLINE_CONFLICT`. 깨지는 시나리오: 화면이 금액 사본을 들고 있다가 차감액과
    어긋난다."""
    _, novel_id = await _novel_setup(db_client, db_session, monkeypatch, turns=2)
    monkeypatch.setattr(settings, "novelize_outline_max_episodes", 7)

    state = (await db_client.get(f"/novels/{novel_id}/outline")).json()

    assert (state["approved"], state["draft"], state["maxEpisodes"]) == (None, None, 7)
    assert state["models"] == [{"id": "gemini", "name": "Gemini", "cost": 11}]
    assert _code(await _approve(db_client, novel_id, 1)) == (409, "NOVEL_OUTLINE_CONFLICT")
