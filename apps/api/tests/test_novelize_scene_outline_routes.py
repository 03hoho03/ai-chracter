"""화별 장면 구성안과 구성 흐름 원고 — 장면 구성안 요청(과금)·실행·리비전·편집·승인, 승인된 장면 구성안으로 쓰는 원고(과금)와
장면 경계 저장, 구성 흐름 화의 다시 만들기. 구성 흐름 스위치가 꺼져 있으면 새 라우트는 모두 404 다.

방은 `_novel_setup` 이 만든다(잔액 100). 메시지는 오프닝 하나 + 6턴이라 키 순 목록 `ms` 에서 `ms[0]` 이 오프닝(모델 응답),
`ms[2k-1]`·`ms[2k]` 가 k번째 사용자 말·응답이다. 선택(`_SECTIONS`)은 include `ms[0..4]` · context `ms[5..6]` · 고르지 않은
`ms[7..8]`(exclude) · include `ms[9..12]` 이다. 전체 구성안은 두 화 — 1화 근거 `ms[0..2]`, 2화 근거 `ms[3..4]`·`ms[9..12]`(두 include
구간에 걸친다)다. 장면 구성안의 턴 번호는 그 화 근거 안에서 1부터 센다(2화: 1턴 = `ms[3..4]`, 2턴 = `ms[9..10]`, 3턴 =
`ms[11..12]`).

요청 라우트는 작업을 띄우는 함수를 기록용으로 바꿔 끼우고, 실행은 그 작업을 `runner.run_job` 에 가짜 모델로 넘겨 이어 본다."""

import re
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from typing import Any

import httpx
import pytest
import sqlalchemy as sa
from pydantic import TypeAdapter
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from api.core import clover
from api.core.config import settings
from api.db.models import ChatMessage, ChatRoom, Content, NovelJob
from api.db.models.chat import ChatMessageRole
from api.db.models.novel import (
    Novel,
    NovelBatch,
    NovelChapter,
    NovelChapterRevision,
    NovelEpisodeOutline,
    NovelSceneBlock,
)
from api.llm.client import LLMCallContext, LLMClient, LLMClientError, T
from api.novelize import router as novelize_router
from api.novelize import runner
from api.novelize.source import segment_hash
from factories import (
    _add_chapter,
    _allow_novel_premium,
    _batch_output,
    _clear_llm_override,
    _make_user,
    _novel_ledger,
    _novel_setup,
    _override_llm_client,
    _room_messages,
    _run_worker_one_pass,
)

_EXCLUDED = "빼기로-한-구간-표지"
_CONTEXT = "맥락으로만-보낸-구간-표지"
_SECTIONS = (("include", 0, 4), ("context", 5, 6), ("include", 9, 12))
_TWO_EPISODES = [
    {"title": "첫 만남", "summary": "둘이 처음 만났다.", "goal": "서로를 궁금해한다.", "start_turn": 1, "end_turn": 2},
    {"title": "다시 만남", "summary": "둘이 다시 만났다.", "goal": "약속을 남긴다.", "start_turn": 3, "end_turn": 5},
]
_PARAGRAPH = "비가 그치지 않는 저녁이었다. 서진은 정류장 지붕 아래에서 오래 서 있었다. " * 4
_BODY = "\n\n".join(f"{n}번째 문단. {_PARAGRAPH}" for n in range(1, 7))
_TURN = re.compile(r"^\[턴 (\d+)\]", re.MULTILINE)


def _scene(title: str, start: int, end: int, **changes: Any) -> dict[str, Any]:
    scene = {
        "title": title,
        "summary": f"{title} 장면에서 일이 일어났다.",
        "purpose": f"{title} 뒤에 무엇이 달라진다.",
        "characters": ["서진", "도윤"],
        "flashback": False,
        "start_turn": start,
        "end_turn": end,
    }
    scene.update(changes)
    return scene


class _FlowLLM(LLMClient):
    """구성 흐름 세 호출을 받는다 — 전체 구성안·장면 구성안(지시문 있는 구조화)과 원고(스트림). 받은 본문·지시문·사용 맥락을 `calls` 에
    (종류, 본문, 지시문, 맥락)로 적는다. 장면 구성안은 `scenes` 가 있으면 그것을, 없으면 원문 줄의 턴 수로 두 장면(1턴 / 2턴~끝)을
    돌려준다. `error` 가 있으면 다음 호출 하나가 그것을 내고, `on_call` 이 있으면 응답 전에 부른다(호출 도중 사용자가 무엇을 바꾸는
    경합)."""

    def __init__(self) -> None:
        self.episodes: list[dict[str, Any]] = _TWO_EPISODES
        self.scenes: list[dict[str, Any]] | None = None
        self.body = _BODY
        self.raw: str | None = None
        self.error: Exception | None = None
        self.on_call: Callable[[], Awaitable[None]] | None = None
        self.calls: list[tuple[str, str, str, LLMCallContext]] = []

    async def _before(self) -> None:
        if self.on_call is not None:
            hook, self.on_call = self.on_call, None
            await hook()
        if self.error is not None:
            error, self.error = self.error, None
            raise error

    async def generate(
        self,
        prompt: str,
        system_instruction: str | None = None,
        stop_sequences: list[str] | None = None,
        *,
        usage: LLMCallContext,
    ) -> AsyncIterator[str]:
        self.calls.append(("chapter", prompt, system_instruction or "", usage))
        await self._before()
        yield self.raw if self.raw is not None else _batch_output(self.body)

    async def generate_structured(
        self, prompt: str, response_schema: Any, images: Any = None, *, usage: LLMCallContext
    ) -> Any:  # pragma: no cover - 불리면 시험 실패
        raise AssertionError("구성 흐름은 지시문 없는 구조화 호출을 쓰지 않는다")

    async def generate_structured_with_instruction(
        self, prompt: str, response_schema: type[T], *, system_instruction: str, usage: LLMCallContext
    ) -> T:
        kind = "scenes" if usage.call_site == "novelize_episode_outline" else "outline"
        self.calls.append((kind, prompt, system_instruction, usage))
        await self._before()
        if kind == "outline":
            return response_schema.model_validate({"episodes": self.episodes})
        last = max(int(n) for n in _TURN.findall(prompt))
        scenes = self.scenes
        if scenes is None:
            scenes = [_scene("시작", 1, 1), _scene("이어짐", 2, last)] if last > 1 else [_scene("시작", 1, 1)]
        return response_schema.model_validate({"scenes": scenes})

    def prompts(self, kind: str) -> list[str]:
        return [prompt + system for k, prompt, system, _ in self.calls if k == kind]


@pytest.fixture
def outline_flow_on(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setattr(settings, "novelize_outline_flow_enabled", True)
    yield


@pytest.fixture(autouse=True)
def _prices(monkeypatch: pytest.MonkeyPatch) -> None:
    """흐름 시험용 고정 단가. 화 단가를 공용 고정값(40)보다 낮춰 잔액 100 안에서 구성안·장면 구성안 둘·원고 둘을 함께 산다."""
    monkeypatch.setattr(clover, "NOVELIZE_OUTLINE_COST", 11)
    monkeypatch.setattr(clover, "NOVELIZE_EPISODE_OUTLINE_COST", 7)
    monkeypatch.setattr(clover, "NOVELIZE_EPISODE_OUTLINE_COST_SONNET", 8)
    monkeypatch.setattr(clover, "NOVELIZE_EPISODE_OUTLINE_COST_OPUS", 9)
    monkeypatch.setattr(clover, "NOVELIZE_EPISODE_COST", 20)


@pytest.fixture
def enqueued(monkeypatch: pytest.MonkeyPatch) -> list[uuid.UUID]:
    """라우트가 띄운 작업 id. 실제로 돌리지는 않는다 — 시험이 `_run` 으로 이어 돌린다."""
    seen: list[uuid.UUID] = []

    async def record(_factory: Any, _llm: Any, job_id: uuid.UUID) -> None:
        seen.append(job_id)

    monkeypatch.setattr(novelize_router, "enqueue_job", record)
    return seen


@pytest.fixture(autouse=True)
def llm() -> Iterator[_FlowLLM]:
    """모든 시험에서 모델 클라이언트를 가짜로 갈아 끼운다(키가 없는 환경에서도 라우트가 클라이언트를 받는다)."""
    fake = _FlowLLM()
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


async def _owner(db: AsyncSession, novel_id: uuid.UUID) -> uuid.UUID:
    owner = await db.scalar(sa.select(Novel.user_id).where(Novel.id == novel_id))
    assert owner is not None
    return owner


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
                {"mode": mode, "startMessageId": str(ms[a].id), "endMessageId": str(ms[b].id)}
                for mode, a, b in sections
            ],
        },
    )
    assert saved.status_code == 200, saved.text
    approved = await db_client.post(f"{base}/approve", json={"revision": saved.json()["draft"]["revision"]})
    assert approved.status_code == 200, approved.text


async def _outlined(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    enqueued: list[uuid.UUID],
    llm: _FlowLLM,
    *,
    sections: tuple[tuple[str, int, int], ...] = _SECTIONS,
    before: Callable[[uuid.UUID, Any, list[ChatMessage]], Awaitable[None]] | None = None,
) -> tuple[uuid.UUID, list[ChatMessage], list[str]]:
    """6턴 방의 소설에 선택을 승인하고 두 화짜리 전체 구성안을 만들어 승인해 둔다. (소설 id, 키 순 메시지, 화 키 둘)."""
    room, novel_id = await _novel_setup(db_client, db_session, monkeypatch, turns=6)
    ms = await _room_messages(db_session, room.room_id)
    if before is not None:
        await before(novel_id, room, ms)
    await _select(db_client, novel_id, ms, sections)
    response = await db_client.post(f"/novels/{novel_id}/outline", json={"model": "gemini", "expectedCost": 11})
    assert response.status_code == 202, response.text
    assert (await _run(db_session, llm, enqueued[-1])).status == "succeeded"
    state = (await db_client.get(f"/novels/{novel_id}/outline")).json()
    approved = await db_client.post(
        f"/novels/{novel_id}/outline/approve", json={"revision": state["draft"]["revision"]}
    )
    assert approved.status_code == 200, approved.text
    return novel_id, ms, [e["key"] for e in approved.json()["approved"]["episodes"]]


def _scenes_url(novel_id: uuid.UUID, key: str) -> str:
    return f"/novels/{novel_id}/outline/episodes/{key}/scenes"


async def _request_scenes(
    db_client: httpx.AsyncClient, novel_id: uuid.UUID, key: str, *, model: str = "gemini", cost: int = 7
) -> httpx.Response:
    return await db_client.post(_scenes_url(novel_id, key), json={"model": model, "expectedCost": cost})


async def _scened(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    enqueued: list[uuid.UUID],
    llm: _FlowLLM,
    novel_id: uuid.UUID,
    key: str,
) -> dict[str, Any]:
    """그 화의 장면 구성안을 만들어 승인하고 승인본을 돌려준다."""
    response = await _request_scenes(db_client, novel_id, key)
    assert response.status_code == 202, response.text
    job = await _run(db_session, llm, enqueued[-1])
    assert job.status == "succeeded", job.failure_code
    state = (await db_client.get(_scenes_url(novel_id, key))).json()
    approved = await db_client.post(
        f"{_scenes_url(novel_id, key)}/approve", json={"revision": state["draft"]["revision"]}
    )
    assert approved.status_code == 200, approved.text
    approved_view: dict[str, Any] = approved.json()["approved"]
    return approved_view


async def _request_chapter(
    db_client: httpx.AsyncClient, novel_id: uuid.UUID, key: str, *, model: str = "gemini", cost: int = 20
) -> httpx.Response:
    return await db_client.post(
        f"/novels/{novel_id}/outline/episodes/{key}/chapter", json={"model": model, "expectedCost": cost}
    )


async def _written(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    enqueued: list[uuid.UUID],
    llm: _FlowLLM,
    novel_id: uuid.UUID,
    key: str,
) -> NovelJob:
    """그 화의 장면 구성안을 승인하고 원고를 써 둔다(성공한 원고 작업)."""
    await _scened(db_client, db_session, enqueued, llm, novel_id, key)
    response = await _request_chapter(db_client, novel_id, key)
    assert response.status_code == 202, response.text
    job = await _run(db_session, llm, enqueued[-1])
    assert job.status == "succeeded", job.failure_code
    return job


async def _scene_rows(db: AsyncSession, chapter_id: uuid.UUID) -> dict[uuid.UUID, str]:
    rows = await db.execute(
        sa.select(NovelSceneBlock.block_id, NovelSceneBlock.scene_id).where(NovelSceneBlock.chapter_id == chapter_id)
    )
    return {block_id: scene_id for block_id, scene_id in rows.all()}


async def _current_revision(db: AsyncSession, chapter_id: uuid.UUID) -> NovelChapterRevision:
    revision = await db.scalar(
        sa.select(NovelChapterRevision)
        .where(NovelChapterRevision.chapter_id == chapter_id)
        .order_by(NovelChapterRevision.revision_no.desc())
        .limit(1)
        .execution_options(populate_existing=True)
    )
    assert revision is not None
    return revision


# ── 스위치 ──────────────────────────────────────────────────────────────────
async def test_every_scene_outline_and_outline_chapter_route_is_a_no_store_404_while_the_flow_switch_is_off(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, enqueued: list[uuid.UUID]
) -> None:
    """스위치가 꺼져 있으면 장면 구성안 조회·요청·저장·승인, 원고 요청, 구성 흐름 다시 만들기가 모두 404
    `NOVEL_OUTLINE_FLOW_DISABLED`(캐시 안 함)이고 차감도 작업도 없다. 깨지는 시나리오: 꺼 둔 운영에서 장면 구성안·원고 값을 받는다."""
    room, novel_id = await _novel_setup(db_client, db_session, monkeypatch, turns=2)
    key = str(uuid.uuid4())
    scenes = _scenes_url(novel_id, key)

    responses = [
        await db_client.get(scenes),
        await db_client.post(scenes, json={"model": "gemini", "expectedCost": 7}),
        await db_client.put(f"{scenes}/draft", json={"baseRevision": 1, "scenes": []}),
        await db_client.post(f"{scenes}/approve", json={"revision": 1}),
        await _request_chapter(db_client, novel_id, key),
        await db_client.post(
            f"/novels/{novel_id}/outline/chapters/{uuid.uuid4()}/regenerate",
            json={"model": "gemini", "expectedCost": 20},
        ),
    ]

    assert [_code(r) for r in responses] == [(404, "NOVEL_OUTLINE_FLOW_DISABLED")] * 6
    assert {r.headers.get("cache-control") for r in responses} == {"no-store"}
    assert enqueued == []
    assert await _novel_ledger(db_session, room.user_id) == []


# ── 장면 구성안: 요청 거절(차감 전) ─────────────────────────────────────────
@pytest.mark.usefixtures("outline_flow_on")
async def test_a_scene_outline_needs_an_approved_outline_holding_that_episode(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, enqueued: list[uuid.UUID]
) -> None:
    """승인한 전체 구성안이 없으면 409 `NOVEL_OUTLINE_REQUIRED`, 승인본에 없는 화 키면 404 `NOVEL_OUTLINE_EPISODE_NOT_FOUND` 이고
    원장에 아무것도 남지 않는다. 깨지는 시나리오: 승인하지 않은 구성안으로 장면 구성안 값을 받는다."""
    room, novel_id = await _novel_setup(db_client, db_session, monkeypatch, turns=2)

    assert _code(await _request_scenes(db_client, novel_id, str(uuid.uuid4()))) == (409, "NOVEL_OUTLINE_REQUIRED")
    assert _code(await db_client.get(_scenes_url(novel_id, str(uuid.uuid4())))) == (409, "NOVEL_OUTLINE_REQUIRED")
    assert enqueued == []
    assert await _novel_ledger(db_session, room.user_id) == []


@pytest.mark.usefixtures("outline_flow_on")
async def test_an_unknown_episode_key_is_not_found(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    enqueued: list[uuid.UUID],
    llm: _FlowLLM,
) -> None:
    """승인본에 없는 화 키는 404 `NOVEL_OUTLINE_EPISODE_NOT_FOUND` 다(조회·요청 모두). 깨지는 시나리오: 키를 지어 낸 요청이 아무 화
    근거로 값을 받는다."""
    novel_id, _, _ = await _outlined(db_client, db_session, monkeypatch, enqueued, llm)
    owner = await _owner(db_session, novel_id)
    key = str(uuid.uuid4())

    assert _code(await _request_scenes(db_client, novel_id, key)) == (404, "NOVEL_OUTLINE_EPISODE_NOT_FOUND")
    assert _code(await db_client.get(_scenes_url(novel_id, key))) == (404, "NOVEL_OUTLINE_EPISODE_NOT_FOUND")
    assert await _novel_ledger(db_session, owner) == [("novelize_spend", -11)]


@pytest.mark.usefixtures("outline_flow_on")
async def test_a_scene_outline_of_a_stale_outline_is_refused_but_an_added_section_keeps_it_usable(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    enqueued: list[uuid.UUID],
    llm: _FlowLLM,
) -> None:
    """승인한 구성안의 근거 include 구간을 뺀 선택을 승인하면 장면 구성안 요청이 409 `NOVEL_OUTLINE_STALE` 이고 차감하지 않는다. 근거
    구간은 그대로 두고 맥락 구간만 넓힌(빼기로 한 사이를 맥락으로 보낸) 선택은 막지 않는다. 깨지는 시나리오: 사용자가 뺀 대화가 옛 구성안을 거쳐
    장면 구성안 입력에 실리거나, 대화를 더 고르기만 해도 구성안을 다시 사야 한다."""
    novel_id, ms, keys = await _outlined(db_client, db_session, monkeypatch, enqueued, llm)
    owner = await _owner(db_session, novel_id)

    await _select(db_client, novel_id, ms, (("include", 0, 4), ("context", 5, 8), ("include", 9, 12)))
    assert (await _request_scenes(db_client, novel_id, keys[1])).status_code == 202
    await db_session.execute(sa.update(NovelJob).where(NovelJob.novel_id == novel_id).values(status="failed"))
    await db_session.commit()

    await _select(db_client, novel_id, ms, (("include", 0, 4), ("include", 9, 10)))
    stale = await _request_scenes(db_client, novel_id, keys[1])

    assert _code(stale) == (409, "NOVEL_OUTLINE_STALE")
    assert await _novel_ledger(db_session, owner) == [("novelize_spend", -11), ("novelize_spend", -7)]


@pytest.mark.usefixtures("outline_flow_on")
async def test_a_scene_outline_whose_episode_became_a_chapter_through_the_old_flow_is_refused(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    enqueued: list[uuid.UUID],
    llm: _FlowLLM,
) -> None:
    """구성안 승인 뒤 그 화의 근거가 옛 흐름의 화가 되었으면 장면 구성안·원고 요청이 422 `NOVEL_SOURCE_SECTION_LOCKED` 이고 차감하지
    않는다. 깨지는 시나리오: 이미 화가 된 대화로 같은 장면을 두 번 산다."""
    novel_id, ms, keys = await _outlined(db_client, db_session, monkeypatch, enqueued, llm)
    owner = await _owner(db_session, novel_id)
    approved = await _scened(db_client, db_session, enqueued, llm, novel_id, keys[0])
    assert approved["revision"] == 1
    room: Any = SimpleNamespace(room_id=ms[0].chat_room_id)
    await _add_chapter(db_session, novel_id, room, ms[3], ms[4])

    assert _code(await _request_scenes(db_client, novel_id, keys[1])) == (422, "NOVEL_SOURCE_SECTION_LOCKED")
    await _add_chapter(db_session, novel_id, room, ms[0], ms[2])
    assert _code(await _request_chapter(db_client, novel_id, keys[0])) == (422, "NOVEL_SOURCE_SECTION_LOCKED")
    assert await _novel_ledger(db_session, owner) == [("novelize_spend", -11), ("novelize_spend", -7)]


@pytest.mark.usefixtures("outline_flow_on")
async def test_a_changed_episode_source_is_refused_before_charging(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    enqueued: list[uuid.UUID],
    llm: _FlowLLM,
) -> None:
    """승인 뒤 화 근거의 원문이 바뀌었으면 409 `NOVEL_SOURCE_SELECTION_SOURCE_CHANGED` 이고 차감하지 않는다. 빼기로 한 사이의 원문이
    바뀐 것은 막지 않는다. 깨지는 시나리오: 사용자가 승인한 것과 다른 원문으로 장면 구성안을 판다."""
    novel_id, ms, keys = await _outlined(db_client, db_session, monkeypatch, enqueued, llm)
    owner = await _owner(db_session, novel_id)
    await _rewrite(db_session, ms[7], _EXCLUDED)
    assert (await _request_scenes(db_client, novel_id, keys[1])).status_code == 202
    await db_session.execute(sa.update(NovelJob).where(NovelJob.novel_id == novel_id).values(status="failed"))
    await db_session.commit()

    await _rewrite(db_session, ms[10], "고친 글")

    assert _code(await _request_scenes(db_client, novel_id, keys[1])) == (409, "NOVEL_SOURCE_SELECTION_SOURCE_CHANGED")
    assert await _novel_ledger(db_session, owner) == [("novelize_spend", -11), ("novelize_spend", -7)]


@pytest.mark.usefixtures("outline_flow_on")
async def test_an_unlocked_novel_of_a_work_that_forbids_novelizing_cannot_buy_scenes_or_a_chapter(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    enqueued: list[uuid.UUID],
    llm: _FlowLLM,
) -> None:
    """아직 첫 화가 없는(잠기지 않은) 소설은 원작의 지금 허락을 다시 본다 — 다른 작가가 소설화를 막았으면 장면 구성안·원고 요청이
    403 `CONTENT_NOVELIZE_FORBIDDEN` 이고 차감하지 않는다. 깨지는 시나리오: 허락을 거둔 원작으로 첫 화 값을 받는다."""
    novel_id, ms, keys = await _outlined(db_client, db_session, monkeypatch, enqueued, llm)
    owner = await _owner(db_session, novel_id)
    await _scened(db_client, db_session, enqueued, llm, novel_id, keys[0])
    content_id = await db_session.scalar(sa.select(ChatRoom.content_id).where(ChatRoom.id == ms[0].chat_room_id))
    creator = _make_user()
    db_session.add(creator)
    await db_session.flush()
    await db_session.execute(
        sa.update(Content)
        .where(Content.id == content_id)
        .values(novel_permission="forbidden", creator_user_id=creator.id)
    )
    await db_session.commit()

    assert _code(await _request_scenes(db_client, novel_id, keys[1])) == (403, "CONTENT_NOVELIZE_FORBIDDEN")
    assert _code(await _request_chapter(db_client, novel_id, keys[0])) == (403, "CONTENT_NOVELIZE_FORBIDDEN")
    assert await _novel_ledger(db_session, owner) == [("novelize_spend", -11), ("novelize_spend", -7)]


# ── 장면 구성안: 요청·실행 ──────────────────────────────────────────────────
@pytest.mark.usefixtures("outline_flow_on")
async def test_a_scene_outline_is_charged_once_run_on_the_episode_basis_and_stored_unapproved(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    enqueued: list[uuid.UUID],
    llm: _FlowLLM,
) -> None:
    """요청은 202 로 진행 대기 작업을 넣고 장면 구성안 고정가를 한 번 깎는다. 실행은 장면 구성안 호출 위치로 고른 모델을 실어 부르고,
    본문에는 그 화의 근거 턴만 1부터 번호를 붙여 싣는다. 모델이 턴 번호로 밝힌 장면 근거는 메시지 구간으로 바뀌어(include 구간마다
    따로) 미승인 리비전 1(출처 generate)로 남는다. 깨지는 시나리오: 다른 화의 대화가 장면 근거에 섞이거나, 장면 근거가 사이의 빼기로 한
    대화를 덮어 원고에 새거나, 장면 구성안이 곧바로 승인된다."""
    novel_id, ms, keys = await _outlined(db_client, db_session, monkeypatch, enqueued, llm)
    owner = await _owner(db_session, novel_id)

    response = await _request_scenes(db_client, novel_id, keys[1])

    assert response.status_code == 202, response.text
    body = response.json()
    assert (body["kind"], body["status"], body["chargedAmount"], body["model"]) == (
        "episode_outline_generate",
        "queued",
        7,
        "gemini",
    )
    job = await _run(db_session, llm, enqueued[-1])
    assert (job.status, job.failure_code) == ("succeeded", None)
    (_, prompt, _, usage) = llm.calls[-1]
    assert (usage.call_site, usage.model, usage.user_id) == ("novelize_episode_outline", "gemini", owner)
    assert sorted({int(n) for n in _TURN.findall(prompt)}) == [1, 2, 3]
    assert "다시 만남" in prompt
    state = (await db_client.get(_scenes_url(novel_id, keys[1]))).json()
    assert state["approved"] is None
    assert state["chapterId"] is None
    draft = state["draft"]
    assert (draft["revision"], draft["source"], draft["model"], draft["stale"]) == (1, "generate", "gemini", False)
    assert [(s["title"], s["flashback"], s["basis"]) for s in draft["scenes"]] == [
        ("시작", False, [_range(ms, 3, 4)]),
        ("이어짐", False, [_range(ms, 9, 12)]),
    ]
    assert len({s["id"] for s in draft["scenes"]}) == 2
    assert {m["id"]: m["cost"] for m in state["models"]} == {"gemini": 7}
    assert {m["id"]: m["cost"] for m in state["chapterModels"]} == {"gemini": 20}
    assert await _novel_ledger(db_session, owner) == [("novelize_spend", -11), ("novelize_spend", -7)]


_BAD_SCENES = {
    "none": [],
    "turn_after_the_last": [_scene("가", 1, 4)],
    "turn_zero": [_scene("가", 0, 1)],
    "reversed_turns": [_scene("가", 2, 1)],
    "overlapping": [_scene("가", 1, 2), _scene("나", 2, 3)],
    "blank_title": [_scene(" ", 1, 3)],
    "blank_summary": [_scene("가", 1, 3, summary=" ")],
}


@pytest.mark.usefixtures("outline_flow_on")
@pytest.mark.parametrize(
    ("case", "failure"),
    [
        pytest.param({"error": LLMClientError("boom")}, "llm_error", id="llm_error"),
        pytest.param(
            {"scenes": [_scene("가", 1, 3, summary="죄송합니다. 이 대화로는 장면 구성안을 만들 수 없습니다.")]},
            "refused",
            id="refusal_text",
        ),
        *(pytest.param({"scenes": bad}, "malformed", id=name) for name, bad in _BAD_SCENES.items()),
    ],
)
async def test_a_failed_or_refused_scene_outline_is_refunded_once_and_stores_nothing(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    enqueued: list[uuid.UUID],
    llm: _FlowLLM,
    case: dict[str, Any],
    failure: str,
) -> None:
    """모델 오류·거절문, 그리고 장면이 없거나 턴 번호가 범위·순서를 벗어나거나 제목·내용이 빈 장면 구성안은 실패로 끝나 전액을 한 번
    돌려주고(원장 짝 1) 장면 구성안 행을 남기지 않는다. 깨지는 시나리오: 쓸 수 없는 장면 구성안에 값을 받는다."""
    novel_id, _, keys = await _outlined(db_client, db_session, monkeypatch, enqueued, llm)
    owner = await _owner(db_session, novel_id)
    llm.error = case.get("error")
    llm.scenes = case.get("scenes")

    assert (await _request_scenes(db_client, novel_id, keys[1])).status_code == 202
    job = await _run(db_session, llm, enqueued[-1])

    assert (job.status, job.failure_code, job.refunded_amount) == ("failed", failure, 7)
    assert await db_session.scalar(sa.select(sa.func.count()).select_from(NovelEpisodeOutline)) == 0
    assert await _novel_ledger(db_session, owner) == [
        ("novelize_spend", -11),
        ("novelize_spend", -7),
        ("novelize_refund", 7),
    ]


@pytest.mark.usefixtures("outline_flow_on")
async def test_a_scene_outline_whose_basis_is_dropped_while_running_is_refunded(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    enqueued: list[uuid.UUID],
    llm: _FlowLLM,
) -> None:
    """모델을 부르는 동안 사용자가 그 화의 근거 구간을 뺀 선택을 승인하면 저장하지 않고 `source_changed` 로 환불한다. 원래 선택을 다시
    승인한 뒤 요청하고 실행 전에 원문이 바뀌면 모델을 부르지 않고 같은 사유로 환불한다. 깨지는 시나리오: 쓸 수 없게 된 장면 구성안에 값을 받는다."""
    novel_id, ms, keys = await _outlined(db_client, db_session, monkeypatch, enqueued, llm)

    async def drop_basis() -> None:
        await _select(db_client, novel_id, ms, (("include", 0, 4),))

    llm.on_call = drop_basis
    assert (await _request_scenes(db_client, novel_id, keys[1])).status_code == 202
    job = await _run(db_session, llm, enqueued[-1])
    assert (job.status, job.failure_code) == ("failed", "source_changed")
    assert await db_session.scalar(sa.select(sa.func.count()).select_from(NovelEpisodeOutline)) == 0

    await _select(db_client, novel_id, ms, _SECTIONS)
    calls = len(llm.calls)
    assert (await _request_scenes(db_client, novel_id, keys[0])).status_code == 202
    await _rewrite(db_session, ms[1], "고친 글")
    job = await _run(db_session, llm, enqueued[-1])
    assert (job.status, job.failure_code) == ("failed", "source_changed")
    assert len(llm.calls) == calls


# ── 장면 구성안: 편집·승인 ──────────────────────────────────────────────────
def _scene_input(scene: dict[str, Any], **changes: Any) -> dict[str, Any]:
    body = {k: scene[k] for k in ("id", "title", "summary", "purpose", "characters", "flashback", "basis")}
    body.update(changes)
    return body


async def _save_scenes(
    db_client: httpx.AsyncClient, novel_id: uuid.UUID, key: str, base: int, scenes: list[dict[str, Any]]
) -> httpx.Response:
    return await db_client.put(f"{_scenes_url(novel_id, key)}/draft", json={"baseRevision": base, "scenes": scenes})


@pytest.mark.usefixtures("outline_flow_on")
async def test_an_edited_scene_outline_is_a_new_revision_that_keeps_scene_ids_and_can_be_reordered(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    enqueued: list[uuid.UUID],
    llm: _FlowLLM,
) -> None:
    """승인본을 고치면 그 위의 새 미승인 리비전(출처 edit)이 되고 승인본은 그대로다. 장면 id 는 유지되고, 나눠 생긴 장면은 새 id 를
    받는다. 순서를 바꿔(회상 장면을 앞에) 저장할 수 있고, 새 판을 승인하면 승인본이 된다. 깨지는 시나리오: 고친 판이 승인본을 덮어
    원고가 사용자가 보지 않은 장면 구성으로 쓰이거나, 장면 id 가 바뀌어 장면 경계가 끊긴다."""
    novel_id, ms, keys = await _outlined(db_client, db_session, monkeypatch, enqueued, llm)
    approved = await _scened(db_client, db_session, enqueued, llm, novel_id, keys[1])
    first, second = approved["scenes"]

    saved = await _save_scenes(
        db_client,
        novel_id,
        keys[1],
        approved["revision"],
        [
            _scene_input(second, basis=[_range(ms, 11, 12)], flashback=True),
            _scene_input(first, title="정류장"),
            _scene_input(second, id=None, title="새 장면", basis=[_range(ms, 9, 10)]),
        ],
    )

    assert saved.status_code == 200, saved.text
    state = saved.json()
    assert state["approved"]["revision"] == approved["revision"]
    assert [s["title"] for s in state["approved"]["scenes"]] == ["시작", "이어짐"]
    draft = state["draft"]
    assert (draft["revision"], draft["source"], draft["model"]) == (2, "edit", None)
    assert [(s["title"], s["flashback"]) for s in draft["scenes"]] == [
        ("이어짐", True),
        ("정류장", False),
        ("새 장면", False),
    ]
    assert [s["id"] for s in draft["scenes"][:2]] == [second["id"], first["id"]]
    assert draft["scenes"][2]["id"] not in {first["id"], second["id"]}
    final = await db_client.post(f"{_scenes_url(novel_id, keys[1])}/approve", json={"revision": 2})
    assert final.status_code == 200
    assert final.json()["approved"]["revision"] == 2
    assert final.json()["draft"] is None


@pytest.mark.usefixtures("outline_flow_on")
@pytest.mark.parametrize(
    ("scenes", "reason"),
    [
        pytest.param(
            lambda ms, s: [_scene_input(s[0], basis=[_range(ms, 0, 2)])], "basis_outside_episode", id="other_episode"
        ),
        pytest.param(
            lambda ms, s: [_scene_input(s[0], basis=[_range(ms, 5, 6)])], "basis_outside_episode", id="context"
        ),
        pytest.param(
            lambda ms, s: [_scene_input(s[0], basis=[_range(ms, 3, 10)])], "basis_outside_episode", id="over_gap"
        ),
        pytest.param(
            lambda ms, s: [
                _scene_input(s[0], basis=[_range(ms, 9, 12)]),
                _scene_input(s[1], basis=[_range(ms, 11, 12)]),
            ],
            "basis_overlap",
            id="overlap",
        ),
        pytest.param(lambda ms, s: [_scene_input(s[0], basis=[_range(ms, 9, 11)])], "basis_splits_turn", id="split"),
        pytest.param(lambda ms, s: [_scene_input(s[0], id=str(uuid.uuid4()))], "unknown_id", id="unknown_id"),
        pytest.param(
            lambda ms, s: [_scene_input(s[0]), _scene_input(s[0], basis=[_range(ms, 9, 10)])], "unknown_id", id="dup"
        ),
    ],
)
async def test_an_edited_scene_outline_must_stay_inside_the_episode_on_turn_boundaries(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    enqueued: list[uuid.UUID],
    llm: _FlowLLM,
    scenes: Callable[[list[ChatMessage], list[dict[str, Any]]], list[dict[str, Any]]],
    reason: str,
) -> None:
    """고친 장면의 근거는 그 화의 근거 구간 하나 안(다른 화·맥락·빼기로 한 사이 밖)에서 턴 경계로 시작·끝나고 장면끼리 겹치지 않아야
    한다. 장면 id 는 기준 판의 것이거나 비워야 한다. 어기면 422 `NOVEL_EPISODE_OUTLINE_INVALID` + `reason` 이고 리비전이 생기지 않는다.
    깨지는 시나리오: 고친 장면 구성안이 다른 화나 사용자가 뺀 대화를 원고 근거로 끌어온다."""
    novel_id, ms, keys = await _outlined(db_client, db_session, monkeypatch, enqueued, llm)
    approved = await _scened(db_client, db_session, enqueued, llm, novel_id, keys[1])

    response = await _save_scenes(db_client, novel_id, keys[1], approved["revision"], scenes(ms, approved["scenes"]))

    assert response.status_code == 422, response.text
    assert response.json()["detail"] == {"code": "NOVEL_EPISODE_OUTLINE_INVALID", "reason": reason}
    assert (await db_client.get(_scenes_url(novel_id, keys[1]))).json()["draft"] is None


@pytest.mark.usefixtures("outline_flow_on")
async def test_a_scene_outline_save_on_a_superseded_revision_conflicts(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    enqueued: list[uuid.UUID],
    llm: _FlowLLM,
) -> None:
    """기준 리비전이 가장 최근이 아니면(다른 탭이 먼저 저장) 저장·승인이 409 `NOVEL_EPISODE_OUTLINE_CONFLICT` 다. 깨지는 시나리오:
    낡은 탭의 저장이 먼저 저장한 판을 조용히 덮는다."""
    novel_id, _, keys = await _outlined(db_client, db_session, monkeypatch, enqueued, llm)
    approved = await _scened(db_client, db_session, enqueued, llm, novel_id, keys[1])
    scenes = [_scene_input(s) for s in approved["scenes"]]
    assert (await _save_scenes(db_client, novel_id, keys[1], 1, scenes)).status_code == 200

    stale = await _save_scenes(db_client, novel_id, keys[1], 1, scenes)
    old = await db_client.post(f"{_scenes_url(novel_id, keys[1])}/approve", json={"revision": 1})

    assert _code(stale) == (409, "NOVEL_EPISODE_OUTLINE_CONFLICT")
    assert _code(old) == (409, "NOVEL_EPISODE_OUTLINE_CONFLICT")


@pytest.mark.usefixtures("outline_flow_on")
async def test_a_scene_outline_follows_its_episode_basis_across_outline_edits(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    enqueued: list[uuid.UUID],
    llm: _FlowLLM,
) -> None:
    """전체 구성안을 고쳐 다시 승인해도 그 화의 근거가 같으면(제목만 고침) 장면 구성안은 낡지 않는다. 화의 근거를 바꾸면 장면 구성안이
    낡아(`stale`) 승인·원고 요청이 409 `NOVEL_EPISODE_OUTLINE_STALE` 이다. 깨지는 시나리오: 화 근거가 바뀐 뒤 옛 장면으로 원고를 써
    지금 구성안에 없는 대화가 원고가 되거나, 다른 화 제목만 고쳐도 장면 구성안을 다시 사야 한다."""
    novel_id, ms, keys = await _outlined(db_client, db_session, monkeypatch, enqueued, llm)
    await _scened(db_client, db_session, enqueued, llm, novel_id, keys[0])
    assert (await _request_scenes(db_client, novel_id, keys[1])).status_code == 202
    await _run(db_session, llm, enqueued[-1])
    outline = (await db_client.get(f"/novels/{novel_id}/outline")).json()["approved"]
    episodes = [{k: e[k] for k in ("key", "title", "summary", "goal", "basis")} for e in outline["episodes"]]

    retitled = await db_client.put(
        f"/novels/{novel_id}/outline/draft",
        json={"baseRevision": outline["revision"], "episodes": [{**episodes[0], "title": "새 제목"}, episodes[1]]},
    )
    assert retitled.status_code == 200, retitled.text
    assert (await db_client.post(f"/novels/{novel_id}/outline/approve", json={"revision": 2})).status_code == 200
    state = (await db_client.get(_scenes_url(novel_id, keys[1]))).json()
    assert state["draft"]["stale"] is False
    assert (await db_client.post(f"{_scenes_url(novel_id, keys[1])}/approve", json={"revision": 1})).status_code == 200

    moved = await db_client.put(
        f"/novels/{novel_id}/outline/draft",
        json={"baseRevision": 2, "episodes": [episodes[0], {**episodes[1], "basis": [_range(ms, 9, 12)]}]},
    )
    assert moved.status_code == 200, moved.text
    assert (await db_client.post(f"/novels/{novel_id}/outline/approve", json={"revision": 3})).status_code == 200

    assert (await db_client.get(_scenes_url(novel_id, keys[1]))).json()["approved"]["stale"] is True
    assert (await db_client.get(_scenes_url(novel_id, keys[0]))).json()["approved"]["stale"] is False
    response = await _request_chapter(db_client, novel_id, keys[0])
    assert response.status_code == 202, response.text
    await _run(db_session, llm, enqueued[-1])
    assert _code(await _request_chapter(db_client, novel_id, keys[1])) == (409, "NOVEL_EPISODE_OUTLINE_STALE")


# ── 원고: 요청 거절(차감 전) ────────────────────────────────────────────────
@pytest.mark.usefixtures("outline_flow_on")
async def test_a_chapter_needs_an_approved_scene_outline(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    enqueued: list[uuid.UUID],
    llm: _FlowLLM,
) -> None:
    """승인한 장면 구성안이 없으면(모델이 만든 판을 아직 승인하지 않았어도) 원고 요청이 409 `NOVEL_EPISODE_OUTLINE_REQUIRED` 이고
    차감하지 않는다. 깨지는 시나리오: 사용자가 보지 않은 장면 구성으로 원고 값을 받는다."""
    novel_id, _, keys = await _outlined(db_client, db_session, monkeypatch, enqueued, llm)
    owner = await _owner(db_session, novel_id)

    assert _code(await _request_chapter(db_client, novel_id, keys[0])) == (409, "NOVEL_EPISODE_OUTLINE_REQUIRED")
    assert (await _request_scenes(db_client, novel_id, keys[0])).status_code == 202
    await _run(db_session, llm, enqueued[-1])
    assert _code(await _request_chapter(db_client, novel_id, keys[0])) == (409, "NOVEL_EPISODE_OUTLINE_REQUIRED")
    assert await _novel_ledger(db_session, owner) == [("novelize_spend", -11), ("novelize_spend", -7)]


@pytest.mark.usefixtures("outline_flow_on")
async def test_chapters_are_written_in_outline_order(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    enqueued: list[uuid.UUID],
    llm: _FlowLLM,
) -> None:
    """원고는 구성안 화 순서대로만 쓴다 — 앞 화가 아직 화가 아니면 409 `NOVEL_OUTLINE_EPISODE_OUT_OF_ORDER` 이고 차감하지 않는다. 앞
    화를 쓴 뒤에는 받는다. 깨지는 시나리오: 화 번호가 구성안 순서와 어긋나 2화 원고가 1화 번호를 받는다."""
    novel_id, _, keys = await _outlined(db_client, db_session, monkeypatch, enqueued, llm)
    owner = await _owner(db_session, novel_id)
    await _scened(db_client, db_session, enqueued, llm, novel_id, keys[1])

    assert _code(await _request_chapter(db_client, novel_id, keys[1])) == (409, "NOVEL_OUTLINE_EPISODE_OUT_OF_ORDER")
    assert await _novel_ledger(db_session, owner) == [("novelize_spend", -11), ("novelize_spend", -7)]
    await _written(db_client, db_session, enqueued, llm, novel_id, keys[0])
    assert (await _request_chapter(db_client, novel_id, keys[1])).status_code == 202


async def _approve_outline_edit(
    db_client: httpx.AsyncClient, novel_id: uuid.UUID, change: Callable[[list[dict[str, Any]]], list[dict[str, Any]]]
) -> None:
    """지금 승인한 전체 구성안의 화 목록을 `change` 로 고쳐 새 리비전으로 저장하고 승인한다."""
    outline = (await db_client.get(f"/novels/{novel_id}/outline")).json()["approved"]
    episodes = [{k: e[k] for k in ("key", "title", "summary", "goal", "basis")} for e in outline["episodes"]]
    saved = await db_client.put(
        f"/novels/{novel_id}/outline/draft", json={"baseRevision": outline["revision"], "episodes": change(episodes)}
    )
    assert saved.status_code == 200, saved.text
    approved = await db_client.post(
        f"/novels/{novel_id}/outline/approve", json={"revision": saved.json()["draft"]["revision"]}
    )
    assert approved.status_code == 200, approved.text


@pytest.mark.usefixtures("outline_flow_on")
async def test_a_chapter_cannot_be_written_before_an_episode_already_written_after_a_reorder(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    enqueued: list[uuid.UUID],
    llm: _FlowLLM,
) -> None:
    """1화를 쓴 뒤 구성안 순서를 바꿔 그 화를 뒤로 옮기면, 앞으로 온 화의 원고는 409 `NOVEL_OUTLINE_EPISODE_OUT_OF_ORDER` 다 — 원고가
    된 화는 늘 구성안의 맨 앞부터 이어져야 한다. 깨지는 시나리오: 구성안은 B→A 인데 화 번호는 A→B 로 굳는다(화 번호는 생성 순서로만
    늘어 바로잡을 수 없다)."""
    novel_id, _, keys = await _outlined(db_client, db_session, monkeypatch, enqueued, llm)
    await _written(db_client, db_session, enqueued, llm, novel_id, keys[0])
    await _scened(db_client, db_session, enqueued, llm, novel_id, keys[1])
    owner = await _owner(db_session, novel_id)
    before = await _novel_ledger(db_session, owner)

    await _approve_outline_edit(db_client, novel_id, lambda episodes: [episodes[1], episodes[0]])

    assert _code(await _request_chapter(db_client, novel_id, keys[1])) == (409, "NOVEL_OUTLINE_EPISODE_OUT_OF_ORDER")
    assert await _novel_ledger(db_session, owner) == before


@pytest.mark.usefixtures("outline_flow_on")
async def test_a_chapter_whose_episode_basis_is_edited_while_running_is_refunded_without_a_chapter(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    enqueued: list[uuid.UUID],
    llm: _FlowLLM,
) -> None:
    """원고 모델을 부르는 동안 사용자가 그 화의 근거를 고친 구성안을 승인하면 저장하지 않고 `source_changed` 로 전액 환불한다. 깨지는
    시나리오: 옛 근거로 쓴 원고가 그 화를 "원고 됨"으로 굳혀, 새 근거에만 있는 대화가 다시 쓸 수도 잠기지도 않고 빠진다."""
    novel_id, ms, keys = await _outlined(db_client, db_session, monkeypatch, enqueued, llm)
    await _scened(db_client, db_session, enqueued, llm, novel_id, keys[0])

    async def narrow_basis() -> None:
        await _approve_outline_edit(
            db_client, novel_id, lambda episodes: [{**episodes[0], "basis": [_range(ms, 0, 0)]}, episodes[1]]
        )

    llm.on_call = narrow_basis
    assert (await _request_chapter(db_client, novel_id, keys[0])).status_code == 202
    job = await _run(db_session, llm, enqueued[-1])

    assert (job.status, job.failure_code, job.refunded_amount) == ("failed", "source_changed", 20)
    assert await db_session.scalar(sa.select(sa.func.count()).select_from(NovelChapter)) == 0


@pytest.mark.usefixtures("outline_flow_on")
async def test_a_chapter_over_the_models_turn_cap_is_refused_before_charging(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    enqueued: list[uuid.UUID],
    llm: _FlowLLM,
) -> None:
    """원고가 쓸 턴 수가 고른 모델의 턴 상한을 넘으면 409 `NOVEL_MODEL_INELIGIBLE` + `too_many_turns` 이고 차감하지 않는다. 깨지는
    시나리오: 작업 시간 상한 안에 쓸 수 없는 분량에 값을 받고 시간 초과로 환불만 남는다."""
    novel_id, _, keys = await _outlined(db_client, db_session, monkeypatch, enqueued, llm)
    owner = await _owner(db_session, novel_id)
    await _scened(db_client, db_session, enqueued, llm, novel_id, keys[0])
    monkeypatch.setattr(settings, "novelize_chapter_max_turns", 1)

    response = await _request_chapter(db_client, novel_id, keys[0])

    assert response.status_code == 409
    assert response.json()["detail"] == {"code": "NOVEL_MODEL_INELIGIBLE", "reason": "too_many_turns"}
    assert await _novel_ledger(db_session, owner) == [("novelize_spend", -11), ("novelize_spend", -7)]


# ── 원고: 요청·실행·저장 ────────────────────────────────────────────────────
@pytest.mark.usefixtures("outline_flow_on")
async def test_a_chapter_is_written_from_the_approved_scenes_with_range_columns_and_scene_boundaries(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    enqueued: list[uuid.UUID],
    llm: _FlowLLM,
) -> None:
    """원고는 화 단가를 한 번 깎고 화 생성 호출 위치로 고른 모델을 실어 부른다. 본문에는 장면 계획(장면 제목)과 장면이 쓰는 턴이 실린다.
    저장된 화는 다음 화 번호를 받고 그 장면 구성안을 가리키며, 옛 코드가 읽는 구간 칸은 장면이 쓴 원문의 첫·끝 메시지·응답 수·해시로
    채워진다. 화 하나짜리 묶음이 함께 생기고, 첫 화라 집필권이 잠긴다. 새 개정의 블록마다 장면 경계 행이 있고 장면은 장면 구성안
    순서대로 이어진다(첫 블록은 첫 장면, 끝 블록은 끝 장면). 깨지는 시나리오: 옛 코드가 빈 구간 칸에 걸려 500 을 내거나, 장면 경계가
    빠져 같은 장면 묶음 수정이 화 전체로 번진다."""
    novel_id, ms, keys = await _outlined(db_client, db_session, monkeypatch, enqueued, llm)
    owner = await _owner(db_session, novel_id)
    approved = await _scened(db_client, db_session, enqueued, llm, novel_id, keys[1])
    await _written(db_client, db_session, enqueued, llm, novel_id, keys[0])

    response = await _request_chapter(db_client, novel_id, keys[1])

    assert response.status_code == 202, response.text
    body = response.json()
    assert (body["kind"], body["chargedAmount"], body["model"]) == ("outline_chapter_generate", 20, "gemini")
    job = await _run(db_session, llm, enqueued[-1])
    assert (job.status, job.failure_code) == ("succeeded", None)
    (kind, prompt, _, usage) = llm.calls[-1]
    assert (kind, usage.call_site, usage.model) == ("chapter", "novelize_chapter", "gemini")
    assert "시작" in prompt and "이어짐" in prompt
    assert sorted({int(n) for n in _TURN.findall(prompt)}) == [1, 2, 3]

    chapter = await db_session.get_one(NovelChapter, job.chapter_id, populate_existing=True)
    scene_messages = [ms[3], ms[4], ms[9], ms[10], ms[11], ms[12]]
    assert (chapter.ordinal, chapter.episode_index, chapter.assistant_message_count) == (2, 0, 3)
    assert (chapter.start_message_id, chapter.end_message_id) == (ms[3].id, ms[12].id)
    assert chapter.source_hash == segment_hash(scene_messages)
    eo = await db_session.scalar(
        sa.select(NovelEpisodeOutline).where(
            NovelEpisodeOutline.novel_id == novel_id,
            NovelEpisodeOutline.revision == approved["revision"],
            NovelEpisodeOutline.episode_key == uuid.UUID(keys[1]),
        )
    )
    assert eo is not None and chapter.episode_outline_id == eo.id
    batch = await db_session.get_one(NovelBatch, chapter.batch_id)
    assert (batch.start_message_id, batch.end_message_id, batch.source_hash) == (
        ms[3].id,
        ms[12].id,
        chapter.source_hash,
    )
    assert (job.batch_id, job.episode_outline_id) == (batch.id, eo.id)
    revision = await _current_revision(db_session, chapter.id)
    assert job.result_revision_id == revision.id
    rows = await _scene_rows(db_session, chapter.id)
    scene_ids = [s["id"] for s in approved["scenes"]]
    order = [rows[block] for block in revision.block_ids]
    assert set(rows) == set(revision.block_ids)
    assert (order[0], order[-1]) == (scene_ids[0], scene_ids[1])
    assert order == sorted(order, key=scene_ids.index)
    novel = await db_session.get_one(Novel, novel_id, populate_existing=True)
    assert novel.writing_locked_at is not None
    state = (await db_client.get(_scenes_url(novel_id, keys[1]))).json()
    assert state["chapterId"] == str(chapter.id)
    assert await _novel_ledger(db_session, owner) == [
        ("novelize_spend", -20),
        ("novelize_spend", -20),
        ("novelize_spend", -11),
        ("novelize_spend", -7),
        ("novelize_spend", -7),
    ]


@pytest.mark.usefixtures("outline_flow_on")
async def test_a_chapter_output_with_two_episodes_is_refunded_without_a_chapter(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    enqueued: list[uuid.UUID],
    llm: _FlowLLM,
) -> None:
    """원고는 장면 구성안 하나로 화 하나다 — 모델이 두 화를 내면 `malformed` 로 전액 환불하고 화를 만들지 않는다. 깨지는 시나리오: 화
    단가 하나로 두 화를 받아 같은 구성안 화가 둘이 된다."""
    novel_id, _, keys = await _outlined(db_client, db_session, monkeypatch, enqueued, llm)
    await _scened(db_client, db_session, enqueued, llm, novel_id, keys[0])
    llm.raw = _batch_output(_BODY, _BODY)

    assert (await _request_chapter(db_client, novel_id, keys[0])).status_code == 202
    job = await _run(db_session, llm, enqueued[-1])

    assert (job.status, job.failure_code, job.refunded_amount) == ("failed", "malformed", 20)
    assert await db_session.scalar(sa.select(sa.func.count()).select_from(NovelChapter)) == 0


@pytest.mark.usefixtures("outline_flow_on")
async def test_an_episode_already_written_cannot_be_bought_again_even_with_a_new_scene_revision(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    enqueued: list[uuid.UUID],
    llm: _FlowLLM,
) -> None:
    """원고가 된 화는 다시 원고를 살 수 없다 — 409 `NOVEL_OUTLINE_EPISODE_WRITTEN`. 장면 구성안을 고쳐 새 리비전을 승인해도 같은 화
    키라 막히고, 그 화의 장면 구성안도 새로 살 수 없다. 깨지는 시나리오: 낡은 화면이 같은 화를 두 번 사서 끝에 같은 화가 붙는다."""
    novel_id, _, keys = await _outlined(db_client, db_session, monkeypatch, enqueued, llm)
    owner = await _owner(db_session, novel_id)
    await _written(db_client, db_session, enqueued, llm, novel_id, keys[0])

    assert _code(await _request_chapter(db_client, novel_id, keys[0])) == (409, "NOVEL_OUTLINE_EPISODE_WRITTEN")
    state = (await db_client.get(_scenes_url(novel_id, keys[0]))).json()
    scenes = [_scene_input(s) for s in state["approved"]["scenes"]]
    saved = await _save_scenes(db_client, novel_id, keys[0], state["approved"]["revision"], scenes)
    assert saved.status_code == 200, saved.text
    assert (await db_client.post(f"{_scenes_url(novel_id, keys[0])}/approve", json={"revision": 2})).status_code == 200

    assert _code(await _request_chapter(db_client, novel_id, keys[0])) == (409, "NOVEL_OUTLINE_EPISODE_WRITTEN")
    assert _code(await _request_scenes(db_client, novel_id, keys[0])) == (409, "NOVEL_OUTLINE_EPISODE_WRITTEN")
    assert await _novel_ledger(db_session, owner) == [
        ("novelize_spend", -20),
        ("novelize_spend", -11),
        ("novelize_spend", -7),
    ]


@pytest.mark.usefixtures("outline_flow_on")
async def test_an_existing_novel_switches_to_the_outline_flow_after_its_old_chapters(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    enqueued: list[uuid.UUID],
    llm: _FlowLLM,
) -> None:
    """옛 흐름 화가 둘 있는 소설도 그 뒤 구간을 골라 구성안 → 장면 구성안 → 원고로 다음 화를 쓴다 — 화 번호 3, `NOVEL_NOTHING_NEW`
    없음. 깨지는 시나리오: 마지막 화 끝 뒤 시작만 받는 옛 검사가 새 흐름 원고를 막아 구성안 값만 치르고 화를 못 만든다."""

    async def two_old_chapters(novel_id: uuid.UUID, room: Any, ms: list[ChatMessage]) -> None:
        await _add_chapter(db_session, novel_id, room, ms[0], ms[2])
        await _add_chapter(db_session, novel_id, room, ms[3], ms[4])

    llm.episodes = [{**_TWO_EPISODES[0], "start_turn": 1, "end_turn": 2}]
    novel_id, ms, keys = await _outlined(
        db_client,
        db_session,
        monkeypatch,
        enqueued,
        llm,
        sections=(("include", 9, 12),),
        before=two_old_chapters,
    )

    job = await _written(db_client, db_session, enqueued, llm, novel_id, keys[0])

    chapter = await db_session.get_one(NovelChapter, job.chapter_id)
    assert (chapter.ordinal, chapter.start_message_id, chapter.end_message_id) == (3, ms[9].id, ms[12].id)


@pytest.mark.usefixtures("outline_flow_on")
async def test_a_chapter_whose_source_changes_after_the_request_is_refunded_without_a_chapter(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    enqueued: list[uuid.UUID],
    llm: _FlowLLM,
) -> None:
    """요청 뒤 실행 전에 원문이 바뀌면 모델을 부르지 않고 `source_changed` 로 전액 환불하고 화를 만들지 않는다. 깨지는 시나리오: 사용자가
    승인하지 않은 원문으로 원고를 쓴다."""
    novel_id, ms, keys = await _outlined(db_client, db_session, monkeypatch, enqueued, llm)
    await _scened(db_client, db_session, enqueued, llm, novel_id, keys[0])
    assert (await _request_chapter(db_client, novel_id, keys[0])).status_code == 202
    calls = len(llm.calls)
    await _rewrite(db_session, ms[2], "고친 글")

    job = await _run(db_session, llm, enqueued[-1])

    assert (job.status, job.failure_code, job.refunded_amount) == ("failed", "source_changed", 20)
    assert len(llm.calls) == calls
    assert await db_session.scalar(sa.select(sa.func.count()).select_from(NovelChapter)) == 0


@pytest.mark.usefixtures("outline_flow_on")
async def test_the_excluded_gap_never_reaches_any_outline_flow_builder(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    enqueued: list[uuid.UUID],
    llm: _FlowLLM,
) -> None:
    """빼기로 한 사이(`ms[7..8]`)에 심은 표지는 장면 구성안·원고·다시 만들기 어느 호출의 지시문·본문에도 없다(0회). 맥락 구간의
    표지는 번호 붙은 원문 줄(`[턴 n]`)에 없다. 깨지는 시나리오: 두 include 구간에 걸친 화를 이어 읽어 사용자가 뺀 대화가 모델에 간다."""

    async def plant(novel_id: uuid.UUID, room: Any, ms: list[ChatMessage]) -> None:
        for message in (ms[7], ms[8]):
            await _rewrite(db_session, message, _EXCLUDED)
        await _rewrite(db_session, ms[5], _CONTEXT)

    novel_id, _, keys = await _outlined(db_client, db_session, monkeypatch, enqueued, llm, before=plant)
    await _written(db_client, db_session, enqueued, llm, novel_id, keys[0])
    job = await _written(db_client, db_session, enqueued, llm, novel_id, keys[1])
    regenerated = await db_client.post(
        f"/novels/{novel_id}/outline/chapters/{job.chapter_id}/regenerate", json={"model": "gemini", "expectedCost": 20}
    )
    assert regenerated.status_code == 202, regenerated.text
    assert (await _run(db_session, llm, enqueued[-1])).status == "succeeded"

    prompts = llm.prompts("scenes") + llm.prompts("chapter")
    assert len(prompts) == 5
    assert all(p.count(_EXCLUDED) == 0 for p in prompts)
    for prompt in prompts:
        assert not any(_CONTEXT in line for line in prompt.splitlines() if line.startswith("[턴 "))
    assert all(_CONTEXT in p for p in llm.prompts("chapter"))


@pytest.mark.usefixtures("outline_flow_on")
async def test_a_written_outline_chapter_locks_only_the_scene_ranges_it_used(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    enqueued: list[uuid.UUID],
    llm: _FlowLLM,
) -> None:
    """두 include 구간에 걸친 구성 흐름 화는 그 장면들이 쓴 구간만 "이미 쓴 구간"으로 잠근다 — 화의 첫·끝 사이(맥락·빼기로 한 사이)를
    통째로 잠그지 않는다. 깨지는 시나리오: 빼기로 한 사이가 이미 쓴 구간으로 묶여 다시 고를 수 없다."""
    novel_id, ms, keys = await _outlined(db_client, db_session, monkeypatch, enqueued, llm)
    await _written(db_client, db_session, enqueued, llm, novel_id, keys[0])
    await _written(db_client, db_session, enqueued, llm, novel_id, keys[1])

    state = (await db_client.get(f"/novels/{novel_id}/source-selection")).json()

    assert state["lockedRanges"] == [_keyed(ms, 0, 0), _keyed(ms, 1, 2), _keyed(ms, 3, 4), _keyed(ms, 9, 12)]


def _keyed(ms: list[ChatMessage], a: int, b: int) -> dict[str, str]:
    """잠긴 구간 응답 하나 — 양 끝 id 와 그 메시지의 `createdAt`(장면 근거에 저장한 글자를 되읽은 값이 방 메시지 키와 같다)."""
    return {
        **_range(ms, a, b),
        "startMessageCreatedAt": _iso(ms[a].created_at),
        "endMessageCreatedAt": _iso(ms[b].created_at),
    }


def _iso(at: datetime) -> str:
    """응답 datetime 의 직렬화 글자(마이크로초가 0 이면 소수부가 없다)."""
    return TypeAdapter(datetime).dump_json(at).decode()[1:-1]


@pytest.mark.usefixtures("outline_flow_on")
async def test_scene_outline_and_manuscript_jobs_carry_the_episode_key_they_work_on(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    enqueued: list[uuid.UUID],
    llm: _FlowLLM,
) -> None:
    """장면 구성안·원고 작업은 요청 응답·폴링·상세의 진행 중 작업에 그 화 키를 싣고, 화 키가 없는 작업(전체 구성안)은 null 이다.
    깨지는 시나리오: 새로고침하거나 다른 탭에서 시작한 작업이 어느 화의 것인지 몰라 그 화에 다시 시도를 줄 수 없다."""
    novel_id, _, keys = await _outlined(db_client, db_session, monkeypatch, enqueued, llm)
    outline_job = enqueued[-1]
    key = keys[0]

    scenes = await _request_scenes(db_client, novel_id, key)
    detail = (await db_client.get(f"/novels/{novel_id}")).json()
    polled = (await db_client.get(f"/novels/{novel_id}/jobs/{enqueued[-1]}")).json()

    assert scenes.status_code == 202, scenes.text
    assert (scenes.json()["episodeKey"], polled["episodeKey"], detail["activeJob"]["episodeKey"]) == (key, key, key)
    assert (await _run(db_session, llm, enqueued[-1])).status == "succeeded"
    state = (await db_client.get(_scenes_url(novel_id, key))).json()
    approved = await db_client.post(f"{_scenes_url(novel_id, key)}/approve", json={"revision": state["draft"]["revision"]})
    assert approved.status_code == 200, approved.text

    chapter = await _request_chapter(db_client, novel_id, key)
    detail = (await db_client.get(f"/novels/{novel_id}")).json()
    polled = (await db_client.get(f"/novels/{novel_id}/jobs/{enqueued[-1]}")).json()

    assert chapter.status_code == 202, chapter.text
    assert (chapter.json()["episodeKey"], polled["episodeKey"], detail["activeJob"]["episodeKey"]) == (key, key, key)
    assert (await db_client.get(f"/novels/{novel_id}/jobs/{outline_job}")).json()["episodeKey"] is None


@pytest.mark.usefixtures("outline_flow_on")
async def test_scenes_are_still_read_for_every_block_after_a_direct_edit_and_a_restore(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    enqueued: list[uuid.UUID],
    llm: _FlowLLM,
) -> None:
    """원고를 직접 고쳐 맨 앞과 중간에 새 문단을 넣어도 블록마다 장면이 읽힌다(맨 앞 새 문단은 뒤의 첫 장면, 중간 새 문단은 앞 문단의
    장면). 처음 개정으로 되돌리면 옛 블록 id 가 돌아와 원고 때와 같은 장면이다. 깨지는 시나리오: 수정·되돌리기 뒤 장면 경계가 끊겨
    같은 장면 묶음 수정이 화 전체로 번진다."""
    from api.novelize.scenes import revision_scenes

    novel_id, _, keys = await _outlined(db_client, db_session, monkeypatch, enqueued, llm)
    job = await _written(db_client, db_session, enqueued, llm, novel_id, keys[0])
    assert job.chapter_id is not None
    first = await _current_revision(db_session, job.chapter_id)
    written = await revision_scenes(db_session, job.chapter_id, first.block_ids)
    paragraphs = first.body.split("\n\n")
    ids: list[str | None] = [str(block) for block in first.block_ids]

    edited = await db_client.post(
        f"/novels/{novel_id}/chapters/{job.chapter_id}/revisions",
        json={
            "baseRevisionId": str(first.id),
            "body": "\n\n".join(["맨 앞에 넣은 문단.", *paragraphs[:3], "가운데 넣은 문단.", *paragraphs[3:]]),
            "blockIds": [None, *ids[:3], None, *ids[3:]],
        },
    )
    assert edited.status_code in (200, 201), edited.text
    second = await _current_revision(db_session, job.chapter_id)
    scenes = await revision_scenes(db_session, job.chapter_id, second.block_ids)
    assert scenes == [written[0], *written[:3], written[2], *written[3:]]

    restored = await db_client.post(
        f"/novels/{novel_id}/chapters/{job.chapter_id}/revisions/{first.id}/restore",
        json={"baseRevisionId": str(second.id)},
    )
    assert restored.status_code in (200, 201), restored.text
    third = await _current_revision(db_session, job.chapter_id)
    assert await revision_scenes(db_session, job.chapter_id, third.block_ids) == written
    assert None not in written


# ── 다시 만들기 ─────────────────────────────────────────────────────────────
@pytest.mark.usefixtures("outline_flow_on")
async def test_an_outline_chapter_is_regenerated_in_place_from_the_same_scene_outline(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    enqueued: list[uuid.UUID],
    llm: _FlowLLM,
) -> None:
    """구성 흐름 화의 다시 만들기는 `chapter_regenerate` 로 화 단가를 깎고, 같은 장면 구성안의 장면 계획으로 쓴 새 개정(출처
    regenerate)을 그 화에 쌓는다 — 화 수는 그대로다. 새 블록마다 장면 경계 행이 생긴다. 깨지는 시나리오: 다시 만들기가 끝에 같은 화를
    하나 더 붙이거나, 장면 계획 없이 다시 써 장면 경계가 끊긴다."""
    novel_id, _, keys = await _outlined(db_client, db_session, monkeypatch, enqueued, llm)
    owner = await _owner(db_session, novel_id)
    job = await _written(db_client, db_session, enqueued, llm, novel_id, keys[0])
    assert job.chapter_id is not None
    llm.body = _BODY.replace("문단.", "다시 쓴 문단.")

    response = await db_client.post(
        f"/novels/{novel_id}/outline/chapters/{job.chapter_id}/regenerate", json={"model": "gemini", "expectedCost": 20}
    )

    assert response.status_code == 202, response.text
    assert (response.json()["kind"], response.json()["chargedAmount"]) == ("chapter_regenerate", 20)
    regenerated = await _run(db_session, llm, enqueued[-1])
    assert (regenerated.status, regenerated.failure_code) == ("succeeded", None)
    (kind, prompt, _, usage) = llm.calls[-1]
    assert (kind, usage.call_site) == ("chapter", "novelize_chapter")
    assert "시작" in prompt and "이어짐" in prompt
    assert await db_session.scalar(sa.select(sa.func.count()).select_from(NovelChapter)) == 1
    revision = await _current_revision(db_session, job.chapter_id)
    assert (revision.revision_no, revision.source, regenerated.result_revision_id) == (2, "regenerate", revision.id)
    assert "다시 쓴 문단" in revision.body
    rows = await _scene_rows(db_session, job.chapter_id)
    assert set(revision.block_ids) <= set(rows)
    assert await _novel_ledger(db_session, owner) == [
        ("novelize_spend", -20),
        ("novelize_spend", -20),
        ("novelize_spend", -11),
        ("novelize_spend", -7),
    ]


@pytest.mark.usefixtures("outline_flow_on")
async def test_with_the_worker_switched_on_an_outline_chapter_regenerate_runs_in_the_worker_from_the_scene_outline(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    enqueued: list[uuid.UUID],
    llm: _FlowLLM,
    tmp_path: Path,
) -> None:
    """워커 스위치가 켜져 있으면 구성 흐름 화의 다시 만들기는 api 가 띄우지 않고 대기 행으로 남고, 소설화 워커가 집어 돌린다.
    종류는 옛 다시 만들기와 같지만 실행 갈래가 다르다 — 워커 경로로 돌려도 api 안에서 돌린 것(위 테스트)과 같이 같은 장면
    구성안의 장면 계획으로 새 개정(출처 regenerate)을 그 화에 쌓고 장면 경계 행을 만든다. 깨지는 시나리오: 워커가 이 행을 집지
    않아 만료 환불로 끝나거나, 장면 구성안 칸을 모르는 옛 다시 만들기 갈래(원문 연속 구간 읽기)로 돌려 실패하거나 장면 경계가
    끊긴 글을 저장한다."""
    novel_id, _, keys = await _outlined(db_client, db_session, monkeypatch, enqueued, llm)
    owner = await _owner(db_session, novel_id)
    job = await _written(db_client, db_session, enqueued, llm, novel_id, keys[0])
    assert job.chapter_id is not None
    llm.body = _BODY.replace("문단.", "다시 쓴 문단.")
    monkeypatch.setattr(settings, "novelize_worker_enabled", True)
    handed_in_process = len(enqueued)

    response = await db_client.post(
        f"/novels/{novel_id}/outline/chapters/{job.chapter_id}/regenerate", json={"model": "gemini", "expectedCost": 20}
    )

    assert response.status_code == 202, response.text
    regenerate_id = uuid.UUID(response.json()["id"])
    assert len(enqueued) == handed_in_process
    assert (await db_session.get_one(NovelJob, regenerate_id, populate_existing=True)).status == "queued"
    claimed = await _run_worker_one_pass(monkeypatch, _factory(db_session), llm, tmp_path / "alive")
    assert claimed == [regenerate_id]
    regenerated = await db_session.get_one(NovelJob, regenerate_id, populate_existing=True)
    assert (regenerated.kind, regenerated.status, regenerated.failure_code) == ("chapter_regenerate", "succeeded", None)
    (kind, prompt, _, usage) = llm.calls[-1]
    assert (kind, usage.call_site) == ("chapter", "novelize_chapter")
    assert "시작" in prompt and "이어짐" in prompt
    assert await db_session.scalar(sa.select(sa.func.count()).select_from(NovelChapter)) == 1
    revision = await _current_revision(db_session, job.chapter_id)
    assert (revision.revision_no, revision.source, regenerated.result_revision_id) == (2, "regenerate", revision.id)
    assert "다시 쓴 문단" in revision.body
    rows = await _scene_rows(db_session, job.chapter_id)
    assert set(revision.block_ids) <= set(rows)
    assert await _novel_ledger(db_session, owner) == [
        ("novelize_spend", -20),
        ("novelize_spend", -20),
        ("novelize_spend", -11),
        ("novelize_spend", -7),
    ]


@pytest.mark.usefixtures("outline_flow_on")
async def test_the_old_regenerate_routes_refuse_an_outline_chapter_and_the_new_one_refuses_an_old_chapter(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    enqueued: list[uuid.UUID],
    llm: _FlowLLM,
) -> None:
    """옛 다시 만들기 라우트(묶음·화)는 구성 흐름 화를 409 `NOVEL_CHAPTER_OUTLINE_FLOW` 로 거절하고, 구성 흐름 다시 만들기는 옛 흐름
    화를 409 `NOVEL_CHAPTER_NOT_OUTLINE_FLOW` 로 거절한다 — 둘 다 차감 전이다. 깨지는 시나리오: 옛 라우트가 장면 계획 없이 연속 구간
    전체(빼기로 한 사이 포함)로 구성 흐름 화를 다시 쓴다."""

    async def old_chapter(novel_id: uuid.UUID, room: Any, ms: list[ChatMessage]) -> None:
        await _add_chapter(db_session, novel_id, room, ms[0], ms[2])

    llm.episodes = [{**_TWO_EPISODES[1], "start_turn": 1, "end_turn": 3}]
    novel_id, _, keys = await _outlined(
        db_client,
        db_session,
        monkeypatch,
        enqueued,
        llm,
        sections=(("include", 3, 4), ("context", 5, 6), ("include", 9, 12)),
        before=old_chapter,
    )
    owner = await _owner(db_session, novel_id)
    job = await _written(db_client, db_session, enqueued, llm, novel_id, keys[0])
    chapter = await db_session.get_one(NovelChapter, job.chapter_id)
    old = await db_session.scalar(
        sa.select(NovelChapter).where(NovelChapter.novel_id == novel_id, NovelChapter.ordinal == 1)
    )
    assert old is not None
    before = await _novel_ledger(db_session, owner)
    body = {"model": "gemini", "expectedCost": 20}

    by_batch = await db_client.post(f"/novels/{novel_id}/batches/{chapter.batch_id}/regenerate", json=body)
    by_chapter = await db_client.post(f"/novels/{novel_id}/chapters/{chapter.id}/regenerate", json=body)
    new_on_old = await db_client.post(f"/novels/{novel_id}/outline/chapters/{old.id}/regenerate", json=body)

    assert _code(by_batch) == (409, "NOVEL_CHAPTER_OUTLINE_FLOW")
    assert _code(by_chapter) == (409, "NOVEL_CHAPTER_OUTLINE_FLOW")
    assert _code(new_on_old) == (409, "NOVEL_CHAPTER_NOT_OUTLINE_FLOW")
    assert await _novel_ledger(db_session, owner) == before


@pytest.mark.usefixtures("outline_flow_on")
async def test_an_outline_chapter_regenerate_refuses_a_changed_context_section_before_charging(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    enqueued: list[uuid.UUID],
    llm: _FlowLLM,
) -> None:
    """다시 만들기도 지금 선택의 맥락 구간 원문이 바뀌었으면 차감 전에 409 `NOVEL_SOURCE_SELECTION_SOURCE_CHANGED` 다(원고 요청과 같다).
    깨지는 시나리오: 누를 때마다 차감되고 실행에서 환불만 되풀이돼, 사용자가 선택을 다시 승인해야 한다는 것을 모른다."""
    novel_id, ms, keys = await _outlined(db_client, db_session, monkeypatch, enqueued, llm)
    owner = await _owner(db_session, novel_id)
    job = await _written(db_client, db_session, enqueued, llm, novel_id, keys[0])
    before = await _novel_ledger(db_session, owner)
    await _rewrite(db_session, ms[5], "고친 맥락")

    response = await db_client.post(
        f"/novels/{novel_id}/outline/chapters/{job.chapter_id}/regenerate", json={"model": "gemini", "expectedCost": 20}
    )

    assert _code(response) == (409, "NOVEL_SOURCE_SELECTION_SOURCE_CHANGED")
    assert await _novel_ledger(db_session, owner) == before


@pytest.mark.usefixtures("outline_flow_on")
async def test_an_outline_chapter_regenerate_refuses_a_changed_source_and_counts_toward_the_scene_outline_daily_cap(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    enqueued: list[uuid.UUID],
    llm: _FlowLLM,
    committing_request_session: None,
) -> None:
    """다시 만들기는 화가 쓴 장면 원문이 바뀌었으면 409 `NOVEL_SOURCE_CHANGED`(차감 전)이고, 하루 상한은 원고와 다시 만들기를 같은 장면
    구성안 리비전으로 함께 센다(상한 1 이면 원고 뒤 다시 만들기가 429 `USER_LIMIT`). 깨지는 시나리오: 바뀐 원문으로 다시 써 원고와
    원문이 어긋나거나, 같은 장면 구성안으로 다시 만들기를 끝없이 산다. 거절한 요청의 되감기가 셋업까지 지우지 않게 요청마다 커밋이 진짜
    경계인 세션으로 돌린다."""
    novel_id, ms, keys = await _outlined(db_client, db_session, monkeypatch, enqueued, llm)
    owner = await _owner(db_session, novel_id)
    job = await _written(db_client, db_session, enqueued, llm, novel_id, keys[0])
    url = f"/novels/{novel_id}/outline/chapters/{job.chapter_id}/regenerate"
    body = {"model": "gemini", "expectedCost": 20}
    before = await _novel_ledger(db_session, owner)
    room_id = ms[0].chat_room_id

    monkeypatch.setattr(settings, "novelize_chapter_daily_limit", 1)
    capped = await db_client.post(url, json=body)
    assert capped.status_code == 429, capped.text
    assert capped.json()["detail"]["code"] == "USER_LIMIT"

    monkeypatch.setattr(settings, "novelize_chapter_daily_limit", 5)
    await _rewrite(db_session, (await _room_messages(db_session, room_id))[1], "고친 글")
    assert _code(await db_client.post(url, json=body)) == (409, "NOVEL_SOURCE_CHANGED")
    assert await _novel_ledger(db_session, owner) == before


# ── 화면이 읽는 칸: 화별 진행·구성 흐름 화 표지·개정의 장면 ─────────────────
def _progress(view: dict[str, Any]) -> list[tuple[str | None, str]]:
    return [(e["chapterId"], e["sceneOutline"]) for e in view["episodes"]]


@pytest.mark.usefixtures("outline_flow_on")
async def test_the_outline_lists_each_episode_with_its_chapter_and_scene_outline_state(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    enqueued: list[uuid.UUID],
    llm: _FlowLLM,
) -> None:
    """전체 구성안의 화마다 원고가 된 화(`chapterId`)와 그 화 장면 구성안의 가장 최근 판 상태(`sceneOutline`)를 싣는다 — 없음 → 초안 →
    승인, 승인 위에 새 초안이 있으면 초안, 화 근거가 바뀌어 낡았으면 초안·승인과 무관하게 낡음. 승인본과 미승인 초안 양쪽 화 목록에 같은
    값이 실린다. 깨지는 시나리오: 화면이 화마다 장면 구성안을 따로 불러야 하거나, 낡은 장면 구성안을 쓸 수 있는 것처럼 보인다."""
    novel_id, ms, keys = await _outlined(db_client, db_session, monkeypatch, enqueued, llm)
    outline_url = f"/novels/{novel_id}/outline"

    async def approved_progress() -> list[tuple[str | None, str]]:
        return _progress((await db_client.get(outline_url)).json()["approved"])

    assert await approved_progress() == [(None, "none"), (None, "none")]
    assert (await _request_scenes(db_client, novel_id, keys[0])).status_code == 202
    await _run(db_session, llm, enqueued[-1])
    assert await approved_progress() == [(None, "draft"), (None, "none")]

    job = await _written(db_client, db_session, enqueued, llm, novel_id, keys[0])
    written = str(job.chapter_id)
    assert await approved_progress() == [(written, "approved"), (None, "none")]

    approved_scenes = (await db_client.get(_scenes_url(novel_id, keys[0]))).json()["approved"]
    resaved = await db_client.put(
        f"{_scenes_url(novel_id, keys[0])}/draft",
        json={
            "baseRevision": approved_scenes["revision"],
            "scenes": [_scene_input(scene) for scene in approved_scenes["scenes"]],
        },
    )
    assert resaved.status_code == 200, resaved.text
    assert (await _request_scenes(db_client, novel_id, keys[1])).status_code == 202
    await _run(db_session, llm, enqueued[-1])
    assert await approved_progress() == [(written, "draft"), (None, "draft")]

    outline = (await db_client.get(outline_url)).json()["approved"]
    episodes = [{k: e[k] for k in ("key", "title", "summary", "goal", "basis")} for e in outline["episodes"]]
    drafted = await db_client.put(
        f"{outline_url}/draft",
        json={"baseRevision": outline["revision"], "episodes": [episodes[0], {**episodes[1], "basis": [_range(ms, 9, 12)]}]},
    )
    assert drafted.status_code == 200, drafted.text
    assert _progress(drafted.json()["draft"]) == [(written, "draft"), (None, "draft")]
    approved = await db_client.post(f"{outline_url}/approve", json={"revision": drafted.json()["draft"]["revision"]})
    assert approved.status_code == 200, approved.text

    assert _progress(approved.json()["approved"]) == [(written, "draft"), (None, "stale")]


@pytest.mark.usefixtures("outline_flow_on")
async def test_the_chapter_list_marks_outline_chapters_even_after_the_flow_switch_is_off(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    enqueued: list[uuid.UUID],
    llm: _FlowLLM,
) -> None:
    """상세 목차의 화마다 구성 흐름 화이면 그 화를 쓴 장면 구성안 리비전 id(`episodeOutlineId`)를, 옛 흐름 화이면 null 을 싣는다.
    스위치를 끈 뒤에도 같다(그 화의 다시 만들기를 막을 근거). 깨지는 시나리오: 구성 흐름 화에 옛 다시 만들기 버튼이 떠 409 가 나거나,
    스위치를 끈 뒤 어느 화가 구성 흐름 화인지 알 길이 없다."""

    async def two_old_chapters(novel_id: uuid.UUID, room: Any, ms: list[ChatMessage]) -> None:
        await _add_chapter(db_session, novel_id, room, ms[0], ms[2])
        await _add_chapter(db_session, novel_id, room, ms[3], ms[4])

    llm.episodes = [{**_TWO_EPISODES[0], "start_turn": 1, "end_turn": 2}]
    novel_id, _, keys = await _outlined(
        db_client, db_session, monkeypatch, enqueued, llm, sections=(("include", 9, 12),), before=two_old_chapters
    )
    job = await _written(db_client, db_session, enqueued, llm, novel_id, keys[0])
    assert job.episode_outline_id is not None
    monkeypatch.setattr(settings, "novelize_outline_flow_enabled", False)

    chapters = (await db_client.get(f"/novels/{novel_id}")).json()["chapters"]

    assert [(c["ordinal"], c["episodeOutlineId"]) for c in chapters] == [
        (1, None),
        (2, None),
        (3, str(job.episode_outline_id)),
    ]


@pytest.mark.usefixtures("outline_flow_on")
async def test_a_revision_lists_its_scenes_with_their_blocks_and_an_old_chapter_has_none(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    enqueued: list[uuid.UUID],
    llm: _FlowLLM,
) -> None:
    """화 조회의 개정은 장면마다 (장면 id, 그 화를 쓴 장면 구성안의 장면 제목, 그 장면의 블록 id 본문 차례)를 장면 차례대로 싣는다 —
    블록 하나는 꼭 한 장면에 든다. 직접 수정으로 새로 생긴 문단도 장면 규칙(맨 앞은 뒤의 첫 장면, 중간은 앞 문단 장면)대로 든다. 장면
    경계가 없는 옛 흐름 화는 빈 목록(화 전체가 한 장면)이다. 깨지는 시나리오: 화면이 다른 장면의 문단을 함께 고르게 둬 서버 422 로만
    막거나, 수정 뒤 새 문단이 어느 장면에도 들지 않는다."""

    async def one_old_chapter(novel_id: uuid.UUID, room: Any, ms: list[ChatMessage]) -> None:
        await _add_chapter(db_session, novel_id, room, ms[0], ms[2])

    llm.episodes = [{**_TWO_EPISODES[0], "start_turn": 1, "end_turn": 2}]
    novel_id, _, keys = await _outlined(
        db_client, db_session, monkeypatch, enqueued, llm, sections=(("include", 9, 12),), before=one_old_chapter
    )
    job = await _written(db_client, db_session, enqueued, llm, novel_id, keys[0])
    assert job.chapter_id is not None
    scenes = (await db_client.get(_scenes_url(novel_id, keys[0]))).json()["approved"]["scenes"]
    assert [scene["title"] for scene in scenes] == ["시작", "이어짐"]
    first = await _current_revision(db_session, job.chapter_id)
    rows = await _scene_rows(db_session, job.chapter_id)
    chapter_url = f"/novels/{novel_id}/chapters/{job.chapter_id}"

    def expected(block_ids: list[uuid.UUID], of: dict[uuid.UUID, str]) -> list[dict[str, Any]]:
        return [
            {"id": scene["id"], "title": scene["title"], "blockIds": [str(b) for b in block_ids if of[b] == scene["id"]]}
            for scene in scenes
        ]

    shown = (await db_client.get(chapter_url)).json()["revision"]["scenes"]
    assert shown == expected(first.block_ids, rows)
    assert all(entry["blockIds"] for entry in shown)

    paragraphs = first.body.split("\n\n")
    ids: list[str | None] = [str(block) for block in first.block_ids]
    edited = await db_client.post(
        f"{chapter_url}/revisions",
        json={
            "baseRevisionId": str(first.id),
            "body": "\n\n".join(["맨 앞에 넣은 문단.", *paragraphs[:3], "가운데 넣은 문단.", *paragraphs[3:]]),
            "blockIds": [None, *ids[:3], None, *ids[3:]],
        },
    )
    assert edited.status_code in (200, 201), edited.text
    second = await _current_revision(db_session, job.chapter_id)
    head, middle = second.block_ids[0], second.block_ids[4]
    inherited = {**rows, head: rows[first.block_ids[0]], middle: rows[first.block_ids[2]]}
    assert edited.json()["revision"]["scenes"] == expected(second.block_ids, inherited)

    old = (await db_client.get(f"/novels/{novel_id}")).json()["chapters"][0]
    assert old["episodeOutlineId"] is None
    assert (await db_client.get(f"/novels/{novel_id}/chapters/{old['id']}")).json()["revision"]["scenes"] == []


# ── 원고 턴 상한: 화 턴 수·모델별 상한·적격 여부·승인 막기 ─────────────────────
def _caps(monkeypatch: pytest.MonkeyPatch, *, gemini: int, sonnet: int, opus: int) -> None:
    monkeypatch.setattr(settings, "novelize_chapter_max_turns", gemini)
    monkeypatch.setattr(settings, "novelize_chapter_max_turns_sonnet", sonnet)
    monkeypatch.setattr(settings, "novelize_chapter_max_turns_opus", opus)


def _inserting_reply(db_session: AsyncSession) -> Callable[[uuid.UUID, Any, list[ChatMessage]], Awaitable[None]]:
    """`ms[2]` 응답 바로 뒤에 사용자 말 없는 응답 하나를 더 넣는 `_outlined` 의 `before` — 응답이 잇달아 있으면 "사용자 말과 그 뒤 응답들"
    묶음 수는 응답 수보다 적다."""

    async def insert(_novel_id: uuid.UUID, room: Any, ms: list[ChatMessage]) -> None:
        db_session.add(
            ChatMessage(
                chat_room_id=room.room_id,
                role=ChatMessageRole.ASSISTANT,
                content="말없이 잠시 뒤에 덧붙인 응답이다.",
                created_at=ms[2].created_at + timedelta(milliseconds=500),
            )
        )
        await db_session.commit()

    return insert


async def _replies_in_basis(db: AsyncSession, room_id: uuid.UUID, basis: list[dict[str, str]]) -> int:
    """근거 구간들 안의 모델 응답 메시지 수 — 화면이 저장 전 화(나눈 조각·합친 결과)를 셀 때 쓰는 세기다."""
    messages = await _room_messages(db, room_id)
    index = {str(m.id): n for n, m in enumerate(messages)}
    return sum(
        1
        for b in basis
        for m in messages[index[b["startMessageId"]] : index[b["endMessageId"]] + 1]
        if m.role == ChatMessageRole.ASSISTANT
    )


def _chapter_model(model: str, name: str, cost: int, max_turns: int, eligible: bool | None) -> dict[str, Any]:
    return {
        "id": model,
        "name": name,
        "cost": cost,
        "maxTurns": max_turns,
        "eligible": eligible,
        "ineligibleReason": "too_many_turns" if eligible is False else None,
    }


def _episode_inputs(view: dict[str, Any]) -> list[dict[str, Any]]:
    return [{k: e[k] for k in ("key", "title", "summary", "goal", "basis")} for e in view["episodes"]]


@pytest.mark.usefixtures("outline_flow_on")
async def test_an_episode_turn_count_is_the_reply_count_the_chapter_turn_cap_refuses_on(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    enqueued: list[uuid.UUID],
    llm: _FlowLLM,
) -> None:
    """구성안 화의 `turnCount` 는 그 화 근거 안의 모델 응답 수이고(여는 응답, 두 구간에 걸친 화, 사용자 말 없이 잇단 응답 포함), 장면
    구성안이 그 화를 빠짐없이 덮으면 장면 구성안 상태의 `chapterTurnCount` 와 같다. 모델별 `eligible` 은 원고 요청의 턴 상한 409 와
    경계(상한 = 턴 수 - 1 / = 턴 수)에서 같다. 깨지는 시나리오: 화면이 고를 수 있다고 보여 준 모델을 요청이 막거나, 화면이 미리 센 턴 수가
    서버 판정과 어긋나 나눌 필요 없는 화를 나누게 한다."""
    novel_id, _, keys = await _outlined(
        db_client, db_session, monkeypatch, enqueued, llm, before=_inserting_reply(db_session)
    )
    room_id = await db_session.scalar(sa.select(Novel.chat_room_id).where(Novel.id == novel_id))
    assert room_id is not None
    episodes = (await db_client.get(f"/novels/{novel_id}/outline")).json()["approved"]["episodes"]

    assert [e["turnCount"] for e in episodes] == [2, 3]
    assert [await _replies_in_basis(db_session, room_id, e["basis"]) for e in episodes] == [2, 3]

    for key, turns in zip(keys, (2, 3), strict=True):
        await _scened(db_client, db_session, enqueued, llm, novel_id, key)
        assert (await db_client.get(_scenes_url(novel_id, key))).json()["chapterTurnCount"] == turns

        _caps(monkeypatch, gemini=turns - 1, sonnet=turns - 1, opus=turns - 1)
        state = (await db_client.get(_scenes_url(novel_id, key))).json()
        assert state["chapterModels"] == [_chapter_model("gemini", "Gemini", 20, turns - 1, False)]
        refused = await _request_chapter(db_client, novel_id, key)
        assert refused.json()["detail"] == {"code": "NOVEL_MODEL_INELIGIBLE", "reason": "too_many_turns"}

        _caps(monkeypatch, gemini=turns, sonnet=turns, opus=turns)
        state = (await db_client.get(_scenes_url(novel_id, key))).json()
        assert state["chapterModels"] == [_chapter_model("gemini", "Gemini", 20, turns, True)]
        accepted = await _request_chapter(db_client, novel_id, key)
        assert accepted.status_code == 202, accepted.text
        assert (await _run(db_session, llm, enqueued[-1])).status == "succeeded"


@pytest.mark.usefixtures("outline_flow_on")
async def test_dropping_a_scene_lowers_the_chapter_turn_count_and_makes_a_model_eligible(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    enqueued: list[uuid.UUID],
    llm: _FlowLLM,
) -> None:
    """장면을 빼서 승인하면 장면 구성안 상태의 턴 수가 준다 — 원고는 장면이 덮은 턴만 쓰기 때문이다. 상한을 넘던 모델이 그 상한 안으로
    들어오면 적격이 된다. 구성안 화의 `turnCount` 는 화 근거로 세므로 그대로다. 깨지는 시나리오: 장면을 덜어 쓸 수 있게 된 화를 화면이 계속
    막거나, 화 근거 수로 판정해 덜기가 소용없어진다."""
    novel_id, _, keys = await _outlined(db_client, db_session, monkeypatch, enqueued, llm)
    approved = await _scened(db_client, db_session, enqueued, llm, novel_id, keys[1])
    _caps(monkeypatch, gemini=2, sonnet=2, opus=2)
    before = (await db_client.get(_scenes_url(novel_id, keys[1]))).json()
    assert (before["chapterTurnCount"], before["chapterModels"][0]["eligible"]) == (3, False)

    saved = await _save_scenes(
        db_client, novel_id, keys[1], approved["revision"], [_scene_input(approved["scenes"][1])]
    )
    assert saved.status_code == 200, saved.text
    after = await db_client.post(
        f"{_scenes_url(novel_id, keys[1])}/approve", json={"revision": saved.json()["draft"]["revision"]}
    )

    assert after.status_code == 200, after.text
    assert after.json()["chapterTurnCount"] == 2
    assert after.json()["chapterModels"] == [_chapter_model("gemini", "Gemini", 20, 2, True)]
    episodes = (await db_client.get(f"/novels/{novel_id}/outline")).json()["approved"]["episodes"]
    assert [e["turnCount"] for e in episodes] == [2, 3]


@pytest.mark.usefixtures("outline_flow_on")
async def test_eligibility_is_unknown_without_a_usable_approved_scene_outline(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    enqueued: list[uuid.UUID],
    llm: _FlowLLM,
) -> None:
    """승인한 장면 구성안이 없거나(초안만 있음 포함) 그 장면 구성안이 낡았으면 원고 턴 수·적격을 판정하지 않는다(null) — 원고 요청도 그때는
    턴 상한보다 장면 구성안 없음·낡음으로 먼저 막힌다. 상한(`maxTurns`)은 늘 싣는다. 깨지는 시나리오: 화면이 판정할 수 없는 화에 "쓸 수
    있음"이나 "못 씀"을 지어 보여 준다."""
    _caps(monkeypatch, gemini=45, sonnet=20, opus=20)
    novel_id, ms, keys = await _outlined(db_client, db_session, monkeypatch, enqueued, llm)
    unknown = [_chapter_model("gemini", "Gemini", 20, 45, None)]

    none = (await db_client.get(_scenes_url(novel_id, keys[0]))).json()
    assert (none["chapterTurnCount"], none["chapterModels"]) == (None, unknown)
    assert (await _request_scenes(db_client, novel_id, keys[0])).status_code == 202
    await _run(db_session, llm, enqueued[-1])
    drafted = (await db_client.get(_scenes_url(novel_id, keys[0]))).json()
    assert (drafted["draft"] is not None, drafted["chapterTurnCount"], drafted["chapterModels"]) == (True, None, unknown)

    await _scened(db_client, db_session, enqueued, llm, novel_id, keys[1])
    outline = (await db_client.get(f"/novels/{novel_id}/outline")).json()["approved"]
    first, second = _episode_inputs(outline)
    drafted_outline = await db_client.put(
        f"/novels/{novel_id}/outline/draft",
        json={"baseRevision": outline["revision"], "episodes": [first, {**second, "basis": [_range(ms, 9, 12)]}]},
    )
    assert drafted_outline.status_code == 200, drafted_outline.text
    assert [e["turnCount"] for e in drafted_outline.json()["draft"]["episodes"]] == [2, 2]
    revision = drafted_outline.json()["draft"]["revision"]
    assert (await db_client.post(f"/novels/{novel_id}/outline/approve", json={"revision": revision})).status_code == 200

    stale = (await db_client.get(_scenes_url(novel_id, keys[1]))).json()
    assert stale["approved"]["stale"] is True
    assert (stale["chapterTurnCount"], stale["chapterModels"]) == (None, unknown)


@pytest.mark.usefixtures("outline_flow_on")
async def test_turn_counts_are_unknown_when_the_room_or_a_basis_end_message_is_gone(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    enqueued: list[uuid.UUID],
    llm: _FlowLLM,
) -> None:
    """근거 끝 메시지가 지워진 화는 `turnCount` 가 null 이고 다른 화는 그대로 센다. 방이 지워지면 모든 화의 `turnCount` 와 장면 구성안
    상태의 판정이 null 이다. 셀 수 없는 화는 승인을 막지 않는다(다음 단계의 원문 검사가 막는다). 깨지는 시나리오: 사라진 대화를 0턴으로
    세어 쓸 수 있는 화처럼 보이거나, 조회·승인이 500 으로 깨져 구성안을 못 연다."""
    novel_id, ms, keys = await _outlined(db_client, db_session, monkeypatch, enqueued, llm)
    await _scened(db_client, db_session, enqueued, llm, novel_id, keys[0])
    outline = (await db_client.get(f"/novels/{novel_id}/outline")).json()["approved"]
    copied = await db_client.put(
        f"/novels/{novel_id}/outline/draft",
        json={"baseRevision": outline["revision"], "episodes": _episode_inputs(outline)},
    )
    assert copied.status_code == 200, copied.text

    await db_session.execute(sa.delete(ChatMessage).where(ChatMessage.id == ms[12].id))
    await db_session.commit()
    episodes = (await db_client.get(f"/novels/{novel_id}/outline")).json()["approved"]["episodes"]
    assert [e["turnCount"] for e in episodes] == [2, None]
    _caps(monkeypatch, gemini=2, sonnet=2, opus=2)
    approved = await db_client.post(
        f"/novels/{novel_id}/outline/approve", json={"revision": copied.json()["draft"]["revision"]}
    )
    assert approved.status_code == 200, approved.text

    await db_session.execute(sa.update(Novel).where(Novel.id == novel_id).values(chat_room_id=None))
    await db_session.commit()
    gone = (await db_client.get(f"/novels/{novel_id}/outline")).json()
    assert [e["turnCount"] for e in gone["approved"]["episodes"]] == [None, None]
    scenes = (await db_client.get(_scenes_url(novel_id, keys[0]))).json()
    assert scenes["chapterTurnCount"] is None
    assert [m["eligible"] for m in scenes["chapterModels"]] == [None]


@pytest.mark.usefixtures("outline_flow_on")
async def test_the_outline_and_scene_states_list_each_available_manuscript_models_turn_cap(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    enqueued: list[uuid.UUID],
    llm: _FlowLLM,
) -> None:
    """구성안 상태의 `chapterTurnCaps` 와 장면 구성안 상태의 원고 모델 `maxTurns` 는 이 계정이 원고에 고를 수 있는 모델과 그 모델의 턴
    상한이다 — 상위 모델 허용이 없으면 기본 모델 하나, 있으면 원고 모델 목록과 같은 순서로 셋. 구성안·장면 구성안 가격 목록에는 칸이
    붙지 않는다. 깨지는 시나리오: 화면이 고를 수 없는 모델의 상한으로 경고하거나, 모델과 상한이 뒤바뀌어 엉뚱한 모델을 막는다."""
    _caps(monkeypatch, gemini=41, sonnet=31, opus=21)
    novel_id, _, keys = await _outlined(db_client, db_session, monkeypatch, enqueued, llm)
    await _scened(db_client, db_session, enqueued, llm, novel_id, keys[0])

    state = (await db_client.get(f"/novels/{novel_id}/outline")).json()
    assert state["chapterTurnCaps"] == [{"id": "gemini", "name": "Gemini", "maxTurns": 41}]

    await _allow_novel_premium(db_session, monkeypatch, await _owner(db_session, novel_id))
    state = (await db_client.get(f"/novels/{novel_id}/outline")).json()
    scenes = (await db_client.get(_scenes_url(novel_id, keys[0]))).json()
    names = {m["id"]: m["name"] for m in scenes["chapterModels"]}

    assert state["chapterTurnCaps"] == [
        {"id": "gemini", "name": "Gemini", "maxTurns": 41},
        {"id": "sonnet", "name": names["sonnet"], "maxTurns": 31},
        {"id": "opus", "name": names["opus"], "maxTurns": 21},
    ]
    assert [(m["id"], m["maxTurns"], m["eligible"]) for m in scenes["chapterModels"]] == [
        ("gemini", 41, True),
        ("sonnet", 31, True),
        ("opus", 21, True),
    ]
    assert all(set(m) == {"id", "name", "cost"} for m in scenes["models"] + state["models"])


async def _generated_draft(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    enqueued: list[uuid.UUID],
    llm: _FlowLLM,
) -> tuple[uuid.UUID, dict[str, Any]]:
    """6턴 방의 소설에 선택을 승인하고 두 화짜리 구성안을 만들어 미승인으로 둔다. (소설 id, 초안)."""
    room, novel_id = await _novel_setup(db_client, db_session, monkeypatch, turns=6)
    ms = await _room_messages(db_session, room.room_id)
    await _select(db_client, novel_id, ms, _SECTIONS)
    response = await db_client.post(f"/novels/{novel_id}/outline", json={"model": "gemini", "expectedCost": 11})
    assert response.status_code == 202, response.text
    assert (await _run(db_session, llm, enqueued[-1])).status == "succeeded"
    draft: dict[str, Any] = (await db_client.get(f"/novels/{novel_id}/outline")).json()["draft"]
    return novel_id, draft


@pytest.mark.usefixtures("outline_flow_on")
async def test_an_outline_with_an_episode_no_available_model_can_write_is_saved_but_not_approved(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    enqueued: list[uuid.UUID],
    llm: _FlowLLM,
) -> None:
    """이 계정이 원고에 고를 수 있는 모델의 가장 큰 턴 상한보다 긴 화가 있으면 승인이 409 `NOVEL_OUTLINE_EPISODE_TOO_LONG` 이고 그 화들의
    키·턴 수와 상한을 싣는다(승인되지 않는다). 고친 판 저장은 막지 않는다. 고를 수 없는 상위 모델의 상한은 세지 않고, 상위 모델을 허용하면
    그 상한으로 승인된다. 이미 승인한 최신 판을 다시 누르면 그대로 돌려준다. 깨지는 시나리오: 어떤 모델로도 원고를 쓸 수 없는 화가 있는
    구성안으로 장면 구성안 값을 받거나, 쓸 수 없는 상위 모델 상한을 믿고 승인시킨다."""
    _caps(monkeypatch, gemini=2, sonnet=3, opus=3)
    novel_id, draft = await _generated_draft(db_client, db_session, monkeypatch, enqueued, llm)
    first, second = draft["episodes"]
    assert [first["turnCount"], second["turnCount"]] == [2, 3]

    resaved = await db_client.put(
        f"/novels/{novel_id}/outline/draft",
        json={"baseRevision": draft["revision"], "episodes": _episode_inputs(draft)},
    )
    assert resaved.status_code == 200, resaved.text
    revision = resaved.json()["draft"]["revision"]
    refused = await db_client.post(f"/novels/{novel_id}/outline/approve", json={"revision": revision})

    assert refused.status_code == 409
    assert refused.json()["detail"] == {
        "code": "NOVEL_OUTLINE_EPISODE_TOO_LONG",
        "maxTurns": 2,
        "episodes": [{"key": second["key"], "turnCount": 3}],
    }
    assert (await db_client.get(f"/novels/{novel_id}/outline")).json()["approved"] is None

    await _allow_novel_premium(db_session, monkeypatch, await _owner(db_session, novel_id))
    approved = await db_client.post(f"/novels/{novel_id}/outline/approve", json={"revision": revision})
    assert approved.status_code == 200, approved.text
    assert approved.json()["approved"]["revision"] == revision

    _caps(monkeypatch, gemini=1, sonnet=1, opus=1)
    again = await db_client.post(f"/novels/{novel_id}/outline/approve", json={"revision": revision})
    assert again.status_code == 200, again.text


@pytest.mark.usefixtures("outline_flow_on")
async def test_an_episode_already_written_does_not_block_approving_a_later_outline_edit(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    enqueued: list[uuid.UUID],
    llm: _FlowLLM,
) -> None:
    """원고가 된 화는 상한보다 길어도 승인을 막지 않는다 — 다시 쓸 화가 아니다(다시 만들기는 그 화가 쓴 장면 구성안으로 따로 판정한다).
    남은 화가 모두 상한 안이면 승인된다. 깨지는 시나리오: 상한을 낮춘 뒤나 장면을 덜어 쓴 화가 있는 소설에서 구성안을 더는 고칠 수 없다."""
    novel_id, ms, keys = await _outlined(db_client, db_session, monkeypatch, enqueued, llm)
    await _written(db_client, db_session, enqueued, llm, novel_id, keys[0])
    outline = (await db_client.get(f"/novels/{novel_id}/outline")).json()["approved"]
    first, second = _episode_inputs(outline)
    split = [
        {**second, "basis": [_range(ms, 3, 4)]},
        {**second, "key": None, "basis": [_range(ms, 9, 10)]},
        {**second, "key": None, "basis": [_range(ms, 11, 12)]},
    ]
    saved = await db_client.put(
        f"/novels/{novel_id}/outline/draft", json={"baseRevision": outline["revision"], "episodes": [first, *split]}
    )
    assert saved.status_code == 200, saved.text
    assert [e["turnCount"] for e in saved.json()["draft"]["episodes"]] == [2, 1, 1, 1]
    _caps(monkeypatch, gemini=1, sonnet=1, opus=1)

    approved = await db_client.post(
        f"/novels/{novel_id}/outline/approve", json={"revision": saved.json()["draft"]["revision"]}
    )

    assert approved.status_code == 200, approved.text
