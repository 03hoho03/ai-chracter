"""소설 작업의 갈래 × 결과를 칸마다 지금 동작 그대로 고정한다 — 버그로 보이는 동작도 고치지 않고 기록한다.

갈래는 실행 경로다: 혼자 도는 장 생성, 연쇄 부모(자식 장 생성 포함), 옛 흐름 묶음 다시 만들기, 구성 흐름 화 다시 만들기, 연속
범위 문단 수정, 여러 문단 수정, 전체 구성안, 장면 구성안, 구성 흐름 원고. 결과는 성공과 실패 사유(잘림·빈 응답·차단·호출 실패·
형식 어긋남·거절·저장 때 낡음·화 수 불일치)와 저장 머리의 만료 경합이다. 칸 키는 `갈래/결과` 다.

칸마다 남기는 것:

- 작업 행 최종 상태 — 상태·실패 사유·낸 금액·돌려준 금액·쓴 몫·결과 본문과 지시문 유무·패치 상태 목록·묶음/화/결과 개정 연결
  유무. 연쇄 부모 칸은 자식 행도 같은 모양으로.
- 이 작업이 만든 원장 행(종류, 금액)과 그 차감의 사용처(종류, 이 소설인가, 방이 있는가)
- 산출 행 모양 — 묶음·화·인물 카드 수, 화마다 개정 출처, 장면 경계 행 수, 구성안·장면 구성안 리비전과 출처, 집필권 잠금 출처,
  소설 제목이 바뀌었는가
- 산출 행 값 — 화마다 제목·요약, 바뀐 소설 제목, 인물 카드 이름, 개정마다 문단 배열 지문(sha256 앞 16자, 본문은 남기지
  않는다), 구성안의 화·장면 구성안의 장면마다 제목·요약. 모두 합성 응답에서 온 값이라 저장 경로가 응답의 어느 칸을 어느 열에
  쓰는지가 바뀌면 칸이 달라진다.
- 가짜 모델이 받은 호출 — 메서드, 응답 스키마 이름, 호출 위치, 실린 모델 두 칸, 프롬프트 지문(본문 + 구분 문자 + 지시문의
  sha256 앞 16자). 문안 본문은 남기지 않는다.
- 소설화 패키지 로거(`api.novelize`, 하위 모듈의 로거가 모두 전파해 온다)의 WARNING 이상 — 렌더된 글에서 첫 `": "` 앞까지(뒤는
  원인 글이라 뺀다). 로거 이름은 남기지 않고 템플릿이 아니라 렌더된 글을 남기는 것은, 같은 글을 내는 경고를 다른 모듈로 옮기거나
  다른 템플릿으로 바꿔도 칸이 그대로여야 해서다.

id 는 처음 나온 순서의 번호로 바꾸고(작업 자신은 `<job>`), 시각은 유무만 남긴다.

작업은 라우트로 만든다(작업을 띄우는 두 함수를 기록 함수로 바꿔 끼운다). 그래야 행의 칸 조합과 프롬프트가 실제 요청 경로의
것이다. 실행은 기록한 id 로 단일 작업 실행 함수를 직접 기다리고, 연쇄 부모는 연쇄 실행 함수를 직접 기다린다. 연쇄 부모를
단일 작업 실행에 넣는 경우는 여기에 두지 않는다 — 그 갈래는 실행 경로가 정할 동작이라 따로 시험한다.

모델 호출 도중의 경합(만료 정리·사용자 편집·선택·구성안 승인)은 가짜 모델이 응답 직전에 부르는 일로 만들고, 그 일이 실제로
닿았는지와 칸이 노린 상태·사유에 닿았는지를 칸마다 먼저 확인한다 — 닿지 않은 채 다른 결과가 기대값으로 굳지 않게.

세션 팩토리는 테스트 커넥션 하나에 SAVEPOINT 로 붙으므로 heartbeat 주기를 크게 늘려 작업 본문과 부딪히지 않게 하고, 만료는
heartbeat 를 과거로 옮겨 만든다(테스트 안 `now()` 는 트랜잭션 시작 시각으로 고정이다).

기대값은 `fixtures/novel_job_matrix.json` 이고 다시 뜨는 법은 `factories._assert_characterization` 이다. 이 파일만의 갱신 변수
`UPDATE_NOVEL_JOB_MATRIX=1` 을 쓰고(채팅 쪽 기대값 파일과 따로 뜬다), 갱신은 xdist 없이(`-n 0`) 돌린다 — 워커 여럿이 같은 기대값
파일을 읽고 고쳐 쓰면 서로의 칸을 덮어쓴다."""

import hashlib
import json
import logging
import os
import re
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from api.core import clover
from api.core.config import settings
from api.db.models import ChatMessage, Novel, NovelChapter, NovelChapterRevision, NovelJob
from api.db.models.clover import CloverLedger, CloverSpendUsage
from api.db.models.novel import (
    NovelBatch,
    NovelCharacter,
    NovelEpisodeOutline,
    NovelJobFailureCode,
    NovelJobStatus,
    NovelOutline,
    NovelSceneBlock,
)
from api.llm.client import (
    LLMCallContext,
    LLMClient,
    LLMClientError,
    LLMEmptyResponseError,
    LLMPolicyViolationError,
    LLMTruncatedError,
    T,
)
from api.novelize import router as novelize_router
from api.novelize import runner
from api.novelize.block_edits import request_targets
from api.novelize.text import split_paragraphs
from factories import (
    Room,
    _add_chapter,
    _assert_characterization,
    _assert_recorded_cases,
    _batch_output,
    _clear_llm_override,
    _episode_text,
    _novel_setup,
    _override_llm_client,
    _room_messages,
    _set_model_price,
    revision_row,
)

pytestmark = pytest.mark.usefixtures("novel_prices_for_flow_tests")

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "novel_job_matrix.json"
UPDATE_ENV = "UPDATE_NOVEL_JOB_MATRIX"

# 합성 문안. 화 본문은 최소 길이(200자)를 넘는다.
_BODY = "비가 내리는 저녁이었다. 서진은 가방을 내려놓고 창가에 섰다.\n\n" + "도윤이 잔을 밀어 주었다. " * 20
_REFUSAL = "죄송하지만 그 요청은 도와드릴 수 없습니다."
_PARAGRAPHS = ["첫 문단이다.", "둘째 문단이다.", "셋째 문단이다.", "넷째 문단이다."]
# 구성 흐름 방(6턴)의 선택 — include 오프닝~2턴 · context 3턴 · 고르지 않은 4턴 · include 5~6턴.
_SECTIONS = (("include", 0, 4), ("context", 5, 6), ("include", 9, 12))
_TWO_EPISODES = [
    {"title": "첫 만남", "summary": "둘이 처음 만났다.", "goal": "서로를 궁금해한다.", "start_turn": 1, "end_turn": 2},
    {"title": "다시 만남", "summary": "둘이 다시 만났다.", "goal": "약속을 남긴다.", "start_turn": 3, "end_turn": 5},
]
_TURN = re.compile(r"^\[턴 (\d+)\]", re.MULTILINE)
_OUTLINE_COST = 11
_SCENES_COST = 7
_EPISODE_COST = 40
_EDIT_COST = 20


def _scene(title: str, start: int, end: int, **changes: Any) -> dict[str, Any]:
    scene: dict[str, Any] = {
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


# ── 가짜 모델 ────────────────────────────────────────────────────────────────
Hook = Callable[[], Awaitable[None]]


class _MatrixLLM(LLMClient):
    """소설 작업의 모든 호출을 받는 가짜. 호출마다 (메서드, 스키마 이름, 호출 위치, 모델, 호출 모델, 프롬프트 지문)을 적는다.

    스트림 호출은 `streams` 를 차례로 흘리고(떨어지면 화 하나), 구조화 호출은 스키마 이름으로 `structured` 에서 응답 dict 를
    고른다(없으면 장면 구성안은 원문 줄의 턴 수로 두 장면, 나머지는 시험 실패). 경계 제안은 늘 실패시켜 턴 상한 끝에서 끊게 한다.
    `errors`·`hooks` 는 경계 제안을 뺀 호출 순번(0부터)으로 고른다 — 그 호출에서 응답 대신 낼 예외와, 응답 직전에 부를 일이다."""

    def __init__(self) -> None:
        self.streams: list[str] = []
        self.structured: dict[str, dict[str, Any]] = {}
        self.errors: dict[int, Exception] = {}
        self.hooks: dict[int, Hook] = {}
        self.calls: list[dict[str, Any]] = []
        self._served = 0

    def _record(self, method: str, schema: str | None, prompt: str, system: str | None, usage: LLMCallContext) -> None:
        digest = hashlib.sha256((prompt + "\x00" + (system or "")).encode("utf-8")).hexdigest()[:16]
        self.calls.append(
            {
                "method": method,
                "schema": schema,
                "callSite": usage.call_site,
                "model": usage.model,
                "callModel": usage.call_model,
                "promptSha": digest,
            }
        )

    async def _before(self) -> None:
        n = self._served
        self._served += 1
        hook = self.hooks.pop(n, None)
        if hook is not None:
            await hook()
        error = self.errors.pop(n, None)
        if error is not None:
            raise error

    async def generate(
        self,
        prompt: str,
        system_instruction: str | None = None,
        stop_sequences: list[str] | None = None,
        *,
        usage: LLMCallContext,
    ) -> AsyncIterator[str]:
        self._record("generate", None, prompt, system_instruction, usage)
        await self._before()
        yield self.streams.pop(0) if self.streams else _batch_output(_BODY)

    async def generate_structured(
        self, prompt: str, response_schema: Any, images: Any = None, *, usage: LLMCallContext
    ) -> Any:
        raise AssertionError("소설 작업은 지시문 없는 구조화 호출을 쓰지 않는다")

    async def generate_structured_with_instruction(
        self, prompt: str, response_schema: type[T], *, system_instruction: str, usage: LLMCallContext
    ) -> T:
        name = response_schema.__name__
        self._record("generate_structured_with_instruction", name, prompt, system_instruction, usage)
        if usage.call_site == "novelize_boundary":
            raise LLMClientError("경계 제안 실패")
        await self._before()
        if name in self.structured:
            return response_schema.model_validate(self.structured[name])
        if name == "NovelizeEpisodeOutlineResult":
            last = max(int(n) for n in _TURN.findall(prompt))
            scenes = [_scene("시작", 1, 1), _scene("이어짐", 2, last)] if last > 1 else [_scene("시작", 1, 1)]
            return response_schema.model_validate({"scenes": scenes})
        raise AssertionError(f"응답을 정하지 않은 스키마: {name}")


def _setup_llm() -> _MatrixLLM:
    """셋업 단계(구성안·장면 구성안·원고를 미리 만들어 둘 때)가 쓰는 가짜 — 모두 성공한다. 칸이 재는 호출과 섞이지 않게 따로 둔다."""
    fake = _MatrixLLM()
    fake.structured["NovelizeOutlineResult"] = {"episodes": _TWO_EPISODES}
    return fake


# ── 칸 문맥 ──────────────────────────────────────────────────────────────────
@dataclass
class _Ctx:
    db_client: httpx.AsyncClient
    db_session: AsyncSession
    monkeypatch: pytest.MonkeyPatch
    factory: async_sessionmaker[AsyncSession]
    enqueued: list[uuid.UUID]
    setup_llm: _MatrixLLM
    room: Room
    novel_id: uuid.UUID
    ms: list[ChatMessage]
    llm: _MatrixLLM = field(default_factory=_MatrixLLM)
    keys: list[str] = field(default_factory=list)
    chapter_id: uuid.UUID | None = None
    cost: int = _EPISODE_COST
    job_id: uuid.UUID | None = None
    # 요청 뒤 실행 전에 부를 일(원문 바꾸기 등).
    before_run: Hook | None = None
    # 경합 장치가 실제로 닿았는지 — (설명, 닿았는가).
    witnesses: list[tuple[str, Callable[[], bool]]] = field(default_factory=list)


def _factory(db_session: AsyncSession) -> async_sessionmaker[AsyncSession]:
    """작업 실행이 여는 세션. SAVEPOINT 로 붙여, 실행 경로의 롤백이 테스트 셋업까지 지우지 않게 한다."""
    return async_sessionmaker(bind=db_session.bind, expire_on_commit=False, join_transaction_mode="create_savepoint")


@pytest.fixture(autouse=True)
def _no_parallel_update() -> None:
    """갱신 모드는 기대값 파일 하나를 읽고 고쳐 쓰므로 xdist 워커에서 돌면 워커끼리 서로의 칸을 덮어쓴다 — 바로 멈춘다."""
    if os.environ.get(UPDATE_ENV) == "1" and os.environ.get("PYTEST_XDIST_WORKER"):
        pytest.fail(f"{UPDATE_ENV}=1 갱신은 워커 여럿이 같은 파일을 덮어쓰므로 -n 0 으로 뜬다")


@pytest.fixture(autouse=True)
def _matrix_settings(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    """heartbeat 는 실행 중에 돌지 않게 늘리고, 만료는 60초로 둔다. 구성 흐름 스위치는 칸의 갈래가 실제로 생기는 값으로 두고(옛 묶음
    생성·연쇄 라우트는 스위치가 켜져 있으면 409 로 거절한다), 여러 문단 수정 스위치는 켠다. 구성안 두 종의 단가를 정한다(화 단가와
    AI 수정 단가는 흐름 시험 공용 고정값)."""
    callspec = getattr(request.node, "callspec", None)
    cell = callspec.params.get("cell") if callspec is not None else None
    outline_flow = cell is None or _BRANCHES[cell.split("/", 1)[0]].outline_flow
    monkeypatch.setattr(settings, "novelize_heartbeat_interval_seconds", 3600)
    monkeypatch.setattr(settings, "novelize_heartbeat_expiry_seconds", 60)
    monkeypatch.setattr(settings, "novelize_outline_flow_enabled", outline_flow)
    monkeypatch.setattr(settings, "novelize_multi_block_edit_enabled", True)
    _set_model_price(monkeypatch, "gemini", novel_outline=_OUTLINE_COST, novel_episode_outline=_SCENES_COST)


@pytest.fixture
def enqueued(monkeypatch: pytest.MonkeyPatch) -> list[uuid.UUID]:
    """라우트가 띄운 작업 id. 실제로 돌리지는 않는다 — 시험이 직접 실행 함수에 넘긴다."""
    seen: list[uuid.UUID] = []

    async def record(_factory: Any, _llm: Any, job_id: uuid.UUID) -> None:
        seen.append(job_id)

    monkeypatch.setattr(novelize_router, "enqueue_job", record)
    monkeypatch.setattr(novelize_router, "enqueue_chain_job", record)
    return seen


def _accepted(response: httpx.Response, enqueued: list[uuid.UUID]) -> uuid.UUID:
    assert response.status_code == 202, response.text
    return enqueued[-1]


async def _base_ctx(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    enqueued: list[uuid.UUID],
    setup_llm: _MatrixLLM,
    *,
    turns: int,
) -> _Ctx:
    """소설화를 허용한 `turns` 턴 방의 소설. 잔액이 칸의 금액에 막히지 않게 클로버를 넉넉히 더 준다."""
    room, novel_id = await _novel_setup(db_client, db_session, monkeypatch, turns=turns)
    await clover.grant(db_session, user_id=room.user_id, amount=1000, kind="admin_grant")
    await db_session.commit()
    ms = await _room_messages(db_session, room.room_id)
    return _Ctx(db_client, db_session, monkeypatch, _factory(db_session), enqueued, setup_llm, room, novel_id, ms)


async def _run(ctx: _Ctx, job_id: uuid.UUID, llm: LLMClient) -> NovelJob:
    await runner.run_job(ctx.factory, llm, job_id)
    return await ctx.db_session.get_one(NovelJob, job_id, populate_existing=True)


# ── 구성 흐름 셋업 ───────────────────────────────────────────────────────────
async def _select(ctx: _Ctx, sections: tuple[tuple[str, int, int], ...]) -> None:
    """선택을 초안으로 저장하고 승인한다(가장 최근 리비전 위에)."""
    base = f"/novels/{ctx.novel_id}/source-selection"
    state = (await ctx.db_client.get(base)).json()
    latest = state["draft"] or state["approved"]
    shown = latest or state["proposal"]
    saved = await ctx.db_client.put(
        f"{base}/draft",
        json={
            "baseRevision": None if latest is None else latest["revision"],
            "extendToRoomEnd": False,
            "roomEndMessageId": shown["roomEndMessageId"],
            "sections": [
                {"mode": mode, "startMessageId": str(ctx.ms[a].id), "endMessageId": str(ctx.ms[b].id)}
                for mode, a, b in sections
            ],
        },
    )
    assert saved.status_code == 200, saved.text
    approved = await ctx.db_client.post(f"{base}/approve", json={"revision": saved.json()["draft"]["revision"]})
    assert approved.status_code == 200, approved.text


async def _approve_outline_edit(ctx: _Ctx, change: Callable[[list[dict[str, Any]]], list[dict[str, Any]]]) -> None:
    """지금 승인한 전체 구성안의 화 목록을 `change` 로 고쳐 새 리비전으로 저장하고 승인한다."""
    outline = (await ctx.db_client.get(f"/novels/{ctx.novel_id}/outline")).json()["approved"]
    episodes = [{k: e[k] for k in ("key", "title", "summary", "goal", "basis")} for e in outline["episodes"]]
    saved = await ctx.db_client.put(
        f"/novels/{ctx.novel_id}/outline/draft", json={"baseRevision": outline["revision"], "episodes": change(episodes)}
    )
    assert saved.status_code == 200, saved.text
    approved = await ctx.db_client.post(
        f"/novels/{ctx.novel_id}/outline/approve", json={"revision": saved.json()["draft"]["revision"]}
    )
    assert approved.status_code == 200, approved.text


def _scenes_url(ctx: _Ctx, key: str) -> str:
    return f"/novels/{ctx.novel_id}/outline/episodes/{key}/scenes"


async def _outlined(ctx: _Ctx) -> None:
    """선택을 승인하고 두 화짜리 전체 구성안을 만들어 승인해 둔다."""
    await _select(ctx, _SECTIONS)
    response = await ctx.db_client.post(
        f"/novels/{ctx.novel_id}/outline", json={"model": "gemini", "expectedCost": _OUTLINE_COST}
    )
    assert (await _run(ctx, _accepted(response, ctx.enqueued), ctx.setup_llm)).status == "succeeded"
    state = (await ctx.db_client.get(f"/novels/{ctx.novel_id}/outline")).json()
    approved = await ctx.db_client.post(
        f"/novels/{ctx.novel_id}/outline/approve", json={"revision": state["draft"]["revision"]}
    )
    assert approved.status_code == 200, approved.text
    ctx.keys = [e["key"] for e in approved.json()["approved"]["episodes"]]


async def _scened(ctx: _Ctx, key: str) -> None:
    """그 화의 장면 구성안을 만들어 승인해 둔다."""
    response = await ctx.db_client.post(_scenes_url(ctx, key), json={"model": "gemini", "expectedCost": _SCENES_COST})
    job = await _run(ctx, _accepted(response, ctx.enqueued), ctx.setup_llm)
    assert job.status == "succeeded", job.failure_code
    state = (await ctx.db_client.get(_scenes_url(ctx, key))).json()
    approved = await ctx.db_client.post(
        f"{_scenes_url(ctx, key)}/approve", json={"revision": state["draft"]["revision"]}
    )
    assert approved.status_code == 200, approved.text


async def _manuscript_request(ctx: _Ctx, key: str) -> httpx.Response:
    return await ctx.db_client.post(
        f"/novels/{ctx.novel_id}/outline/episodes/{key}/chapter", json={"model": "gemini", "expectedCost": ctx.cost}
    )


# ── 갈래: 셋업과 요청 ────────────────────────────────────────────────────────
Prepare = Callable[[_Ctx], Awaitable[None]]
Request = Callable[[_Ctx], Awaitable[uuid.UUID]]


async def _prepare_nothing(ctx: _Ctx) -> None:
    return None


async def _prepare_chain(ctx: _Ctx) -> None:
    # 4턴(오프닝 포함)을 턴 상한 2로 나눠 묶음 둘. 경계 제안이 실패해 묶음마다 상한 끝에서 끊는다.
    ctx.monkeypatch.setattr(settings, "novelize_chapter_max_turns", 2)


async def _prepare_chapter(ctx: _Ctx) -> None:
    """작업을 거치지 않고 오프닝~1턴 구간의 화 하나(네 문단)를 넣는다."""
    chapter = await _add_chapter(
        ctx.db_session, ctx.novel_id, ctx.room, ctx.ms[0], ctx.room.turns[1][1], body="\n\n".join(_PARAGRAPHS)
    )
    ctx.chapter_id = chapter.id
    ctx.llm.structured["NovelizeReviseResult"] = {"paragraphs": ["쓸쓸해진 둘째 문단이다."]}
    ctx.llm.structured["NovelizeBlockEditResult"] = {
        "patches": [{"paragraph": 1, "paragraphs": ["고친 첫째."]}, {"paragraph": 3, "paragraphs": ["고친 셋째."]}],
        "bundles": [],
    }


async def _prepare_outline(ctx: _Ctx) -> None:
    await _select(ctx, _SECTIONS)
    ctx.llm.structured["NovelizeOutlineResult"] = {"episodes": _TWO_EPISODES}


async def _prepare_episode_outline(ctx: _Ctx) -> None:
    await _outlined(ctx)
    # 둘째 화의 근거는 2턴(3~4번 메시지)·5~6턴의 세 턴이다.
    ctx.llm.structured["NovelizeEpisodeOutlineResult"] = {"scenes": [_scene("시작", 1, 1), _scene("이어짐", 2, 3)]}


async def _prepare_manuscript(ctx: _Ctx) -> None:
    await _outlined(ctx)
    await _scened(ctx, ctx.keys[0])


async def _prepare_outline_regenerate(ctx: _Ctx) -> None:
    await _prepare_manuscript(ctx)
    job = await _run(ctx, _accepted(await _manuscript_request(ctx, ctx.keys[0]), ctx.enqueued), ctx.setup_llm)
    assert job.status == "succeeded" and job.chapter_id is not None, job.failure_code
    ctx.chapter_id = job.chapter_id


async def _current_revision(ctx: _Ctx) -> NovelChapterRevision:
    revision = await ctx.db_session.scalar(
        sa.select(NovelChapterRevision)
        .where(NovelChapterRevision.chapter_id == ctx.chapter_id)
        .order_by(NovelChapterRevision.revision_no.desc())
        .limit(1)
        .execution_options(populate_existing=True)
    )
    assert revision is not None
    return revision


async def _request_generate(ctx: _Ctx) -> uuid.UUID:
    response = await ctx.db_client.post(
        f"/novels/{ctx.novel_id}/chapters",
        json={"endMessageId": str(ctx.room.turns[1][1].id), "expectedCost": ctx.cost},
    )
    return _accepted(response, ctx.enqueued)


async def _request_chain(ctx: _Ctx) -> uuid.UUID:
    estimate = await ctx.db_client.get(f"/novels/{ctx.novel_id}/chain-estimate")
    assert estimate.status_code == 200, estimate.text
    (option,) = [o for o in estimate.json()["options"] if o["model"] == "gemini"]
    response = await ctx.db_client.post(
        f"/novels/{ctx.novel_id}/chain",
        json={"model": "gemini", "expectedCost": option["cost"], "maxBatches": option["batchCount"]},
    )
    return _accepted(response, ctx.enqueued)


async def _request_regenerate(ctx: _Ctx) -> uuid.UUID:
    response = await ctx.db_client.post(
        f"/novels/{ctx.novel_id}/chapters/{ctx.chapter_id}/regenerate", json={"expectedCost": ctx.cost}
    )
    return _accepted(response, ctx.enqueued)


async def _request_outline_regenerate(ctx: _Ctx) -> uuid.UUID:
    response = await ctx.db_client.post(
        f"/novels/{ctx.novel_id}/outline/chapters/{ctx.chapter_id}/regenerate",
        json={"model": "gemini", "expectedCost": ctx.cost},
    )
    return _accepted(response, ctx.enqueued)


async def _request_paragraph_edit(ctx: _Ctx) -> uuid.UUID:
    base = await _current_revision(ctx)
    response = await ctx.db_client.post(
        f"/novels/{ctx.novel_id}/chapters/{ctx.chapter_id}/ai-edits",
        json={
            "baseRevisionId": str(base.id),
            "paragraphStart": 1,
            "paragraphEnd": 1,
            "instruction": "더 쓸쓸하게",
            "expectedCost": _EDIT_COST,
        },
    )
    return _accepted(response, ctx.enqueued)


async def _request_block_edit(ctx: _Ctx) -> uuid.UUID:
    base = await _current_revision(ctx)
    response = await ctx.db_client.post(
        f"/novels/{ctx.novel_id}/chapters/{ctx.chapter_id}/block-edits",
        json={
            "baseRevisionId": str(base.id),
            "blockIds": [str(base.block_ids[0]), str(base.block_ids[2])],
            "instruction": "더 쓸쓸하게",
            "expectedCost": _EDIT_COST,
        },
    )
    return _accepted(response, ctx.enqueued)


async def _request_outline(ctx: _Ctx) -> uuid.UUID:
    response = await ctx.db_client.post(
        f"/novels/{ctx.novel_id}/outline", json={"model": "gemini", "expectedCost": _OUTLINE_COST}
    )
    return _accepted(response, ctx.enqueued)


async def _request_episode_outline(ctx: _Ctx) -> uuid.UUID:
    response = await ctx.db_client.post(
        _scenes_url(ctx, ctx.keys[1]), json={"model": "gemini", "expectedCost": _SCENES_COST}
    )
    return _accepted(response, ctx.enqueued)


async def _request_manuscript(ctx: _Ctx) -> uuid.UUID:
    return _accepted(await _manuscript_request(ctx, ctx.keys[0]), ctx.enqueued)


@dataclass(frozen=True)
class _Branch:
    turns: int
    prepare: Prepare
    request: Request
    chain: bool = False
    # 구성 흐름 스위치. 옛 묶음 생성·연쇄 라우트는 스위치가 꺼져 있을 때만 받으므로 그 갈래는 끈다. 옛 다시 만들기와 AI 수정
    # 라우트는 스위치를 보지 않고, 구성 흐름 라우트는 켜져 있어야 받는다.
    outline_flow: bool = True


_BRANCHES: dict[str, _Branch] = {
    "legacy_generate": _Branch(3, _prepare_nothing, _request_generate, outline_flow=False),
    "chain_parent": _Branch(3, _prepare_chain, _request_chain, chain=True, outline_flow=False),
    "legacy_regenerate": _Branch(3, _prepare_chapter, _request_regenerate),
    "outline_regenerate": _Branch(6, _prepare_outline_regenerate, _request_outline_regenerate),
    "paragraph_edit": _Branch(3, _prepare_chapter, _request_paragraph_edit),
    "block_edit": _Branch(3, _prepare_chapter, _request_block_edit),
    "outline": _Branch(6, _prepare_outline, _request_outline),
    "episode_outline": _Branch(6, _prepare_episode_outline, _request_episode_outline),
    "manuscript": _Branch(6, _prepare_manuscript, _request_manuscript),
}


# ── 결과를 만드는 장치 ───────────────────────────────────────────────────────
Arm = Callable[[_Ctx], Awaitable[None]]


async def _as_is(ctx: _Ctx) -> None:
    return None


def _fail_with(error: Exception) -> Arm:
    async def arm(ctx: _Ctx) -> None:
        ctx.llm.errors[0] = error

    return arm


def _fail_with_at(call: int, error: Exception) -> Arm:
    async def arm(ctx: _Ctx) -> None:
        ctx.llm.errors[call] = error

    return arm


def _stream(*outputs: str) -> Arm:
    async def arm(ctx: _Ctx) -> None:
        ctx.llm.streams = list(outputs)

    return arm


def _structured(schema: str, response: dict[str, Any]) -> Arm:
    async def arm(ctx: _Ctx) -> None:
        ctx.llm.structured[schema] = response

    return arm


def _during_call(change: Callable[[_Ctx], Awaitable[None]], description: str, *, call: int = 0) -> Arm:
    """`call` 번째 모델 호출의 응답 직전에 `change` 를 부른다. 불렸는지를 칸이 확인한다."""

    async def arm(ctx: _Ctx) -> None:
        reached: list[bool] = []

        async def hook() -> None:
            await change(ctx)
            reached.append(True)

        ctx.llm.hooks[call] = hook
        ctx.witnesses.append((description, lambda: bool(reached)))

    return arm


def _before_run(change: Callable[[_Ctx], Awaitable[None]]) -> Arm:
    async def arm(ctx: _Ctx) -> None:
        async def run() -> None:
            await change(ctx)

        ctx.before_run = run

    return arm


async def _expire_the_job(ctx: _Ctx) -> None:
    """만료 정리가 먼저 돈다 — heartbeat 를 과거로 옮기고 그 소설의 만료 정리를 커밋한다."""
    assert ctx.job_id is not None
    async with ctx.factory() as s:
        await s.execute(
            sa.update(NovelJob)
            .where(NovelJob.id == ctx.job_id)
            .values(heartbeat_at=sa.func.now() - timedelta(hours=1))
        )
        expired = await runner.expire_stale_jobs(s, novel_id=ctx.novel_id)
        await s.commit()
    ctx.witnesses.append(("만료 정리가 이 작업 하나를 끝냈다", lambda: expired == 1))


async def _end_the_parent_elsewhere(ctx: _Ctx) -> None:
    """자식을 모르는 경로가 연쇄 부모만 끝낸다(환불 시각만 찍는 옛 판 환불과 같은 모양)."""
    assert ctx.job_id is not None
    async with ctx.factory() as s:
        await s.execute(
            sa.update(NovelJob)
            .where(NovelJob.id == ctx.job_id)
            .values(status="failed", failure_code="expired", refunded_at=sa.func.now(), finished_at=sa.func.now())
        )
        await s.commit()


async def _delete_the_end_message(ctx: _Ctx) -> None:
    await ctx.db_session.execute(sa.delete(ChatMessage).where(ChatMessage.id == ctx.room.turns[1][1].id))
    await ctx.db_session.commit()


async def _rewrite_the_opening_turn(ctx: _Ctx) -> None:
    """화 구간(오프닝~1턴) 안의 사용자 말을 고친다 — 그 구간의 원문 해시가 바뀐다."""
    message = ctx.ms[1]
    await ctx.db_session.execute(
        sa.update(ChatMessage).where(ChatMessage.id == message.id).values(content=f"{message.content} 고친 글")
    )
    await ctx.db_session.commit()


async def _edit_the_second_paragraph(ctx: _Ctx) -> None:
    """사용자가 그 화의 둘째 문단을 고친 새 개정을 쌓는다(블록 id 는 그대로)."""
    current = await _current_revision(ctx)
    body = "\n\n".join([_PARAGRAPHS[0], "사용자가 고친 둘째.", *_PARAGRAPHS[2:]])
    ctx.db_session.add(
        revision_row(chapter_id=current.chapter_id, revision_no=current.revision_no + 1, body=body, source="manual_edit")
    )
    await ctx.db_session.commit()


async def _replace_the_whole_chapter(ctx: _Ctx) -> None:
    """사용자가 그 화의 글을 통째로 바꾼 새 개정을 쌓는다(블록 id 도 새로)."""
    current = await _current_revision(ctx)
    ctx.db_session.add(
        revision_row(
            chapter_id=current.chapter_id, revision_no=current.revision_no + 1, body="완전히 다른 글.", source="manual_edit"
        )
    )
    await ctx.db_session.commit()


async def _drop_the_last_include(ctx: _Ctx) -> None:
    await _select(ctx, (("include", 0, 4),))


async def _narrow_the_first_episode_basis(ctx: _Ctx) -> None:
    def narrowed(episodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
        first = ctx.ms[0]
        return [
            {**episodes[0], "basis": [{"startMessageId": str(first.id), "endMessageId": str(first.id)}]},
            *episodes[1:],
        ]

    await _approve_outline_edit(ctx, narrowed)


async def _shortfall_target(ctx: _Ctx) -> None:
    """화 목표 길이를 1자로 줄여 화 수 상한(3화)을 목표로 사게 하고, 한 화만 낸다."""
    ctx.monkeypatch.setattr(settings, "novelize_episode_target_chars", 1)
    ctx.cost = 3 * _EPISODE_COST
    ctx.llm.streams = [_batch_output(_BODY)]


def _call_failures(prefix: str) -> dict[str, tuple[Arm, NovelJobStatus, NovelJobFailureCode | None]]:
    """호출 실패 네 칸 — 잘림·빈 응답·차단·그 밖의 호출 실패."""
    return {
        f"{prefix}/truncated": (_fail_with(LLMTruncatedError("잘림")), "failed", "truncated"),
        f"{prefix}/empty": (_fail_with(LLMEmptyResponseError("빈 응답")), "failed", "empty"),
        f"{prefix}/blocked": (_fail_with(LLMPolicyViolationError("차단")), "failed", "blocked"),
        f"{prefix}/llm_error": (_fail_with(LLMClientError("합성 호출 실패")), "failed", "llm_error"),
    }


# 칸 → (장치, 칸이 노린 작업 행 상태, 실패 사유). 노린 상태·사유는 기대값을 뜨기 전에 적은 예측이고, 칸이 그 자리에 닿았는지의
# 확인이다. 연쇄 부모 칸은 부모 행의 값이다.
_CELLS: dict[str, tuple[Arm, NovelJobStatus, NovelJobFailureCode | None]] = {
    # 혼자 도는 장 생성
    "legacy_generate/succeeded": (_as_is, "succeeded", None),
    "legacy_generate/succeeded_short_of_target": (_shortfall_target, "succeeded", None),
    **_call_failures("legacy_generate"),
    "legacy_generate/malformed_format": (_stream(_episode_text(_BODY, number=2)), "failed", "malformed"),
    "legacy_generate/malformed_over_episode_cap": (_stream(_batch_output(_BODY, _BODY, _BODY, _BODY)), "failed", "malformed"),
    "legacy_generate/refused": (_stream(_batch_output(_REFUSAL)), "failed", "refused"),
    "legacy_generate/source_changed": (_before_run(_delete_the_end_message), "failed", "source_changed"),
    "legacy_generate/expired_during_call": (
        _during_call(_expire_the_job, "생성 호출 도중 만료 정리가 돌았다"),
        "failed",
        "expired",
    ),
    # 연쇄 부모(자식 장 생성 포함)
    "chain_parent/succeeded": (_as_is, "succeeded", None),
    "chain_parent/child_failed": (_fail_with_at(1, LLMClientError("합성 호출 실패")), "failed", "llm_error"),
    "chain_parent/parent_ended_before_child_saved": (
        _during_call(_end_the_parent_elsewhere, "첫 자식 호출 도중 부모가 끝났다"),
        "failed",
        "expired",
    ),
    # 옛 흐름 묶음 다시 만들기
    "legacy_regenerate/succeeded": (_as_is, "succeeded", None),
    "legacy_regenerate/episode_count_mismatch": (
        _stream(_batch_output(_BODY, _BODY)),
        "failed",
        "episode_count_mismatch",
    ),
    "legacy_regenerate/source_changed": (_before_run(_rewrite_the_opening_turn), "failed", "source_changed"),
    **_call_failures("legacy_regenerate"),
    # 구성 흐름 화 다시 만들기
    "outline_regenerate/succeeded": (_as_is, "succeeded", None),
    "outline_regenerate/source_changed": (_before_run(_rewrite_the_opening_turn), "failed", "source_changed"),
    **_call_failures("outline_regenerate"),
    # 연속 범위 문단 수정
    "paragraph_edit/succeeded": (_as_is, "succeeded", None),
    "paragraph_edit/empty_after_parsing": (
        _structured("NovelizeReviseResult", {"paragraphs": ["  "]}),
        "failed",
        "empty",
    ),
    "paragraph_edit/refused": (_structured("NovelizeReviseResult", {"paragraphs": [_REFUSAL]}), "failed", "refused"),
    "paragraph_edit/source_changed": (
        _during_call(_edit_the_second_paragraph, "수정 호출 도중 사용자가 문단을 고쳤다"),
        "failed",
        "source_changed",
    ),
    **_call_failures("paragraph_edit"),
    "paragraph_edit/expired_during_call": (
        _during_call(_expire_the_job, "수정 호출 도중 만료 정리가 돌았다"),
        "failed",
        "expired",
    ),
    # 여러 문단 수정
    "block_edit/succeeded": (_as_is, "succeeded", None),
    "block_edit/empty_no_patches": (
        _structured("NovelizeBlockEditResult", {"patches": [], "bundles": []}),
        "failed",
        "empty",
    ),
    "block_edit/refused": (
        _structured("NovelizeBlockEditResult", {"patches": [{"paragraph": 1, "paragraphs": [_REFUSAL]}], "bundles": []}),
        "failed",
        "refused",
    ),
    "block_edit/source_changed": (
        _during_call(_replace_the_whole_chapter, "수정 호출 도중 사용자가 화를 통째로 바꿨다"),
        "failed",
        "source_changed",
    ),
    **_call_failures("block_edit"),
    # 전체 구성안
    "outline/succeeded": (_as_is, "succeeded", None),
    "outline/malformed": (
        _structured("NovelizeOutlineResult", {"episodes": [{**_TWO_EPISODES[0], "start_turn": 1, "end_turn": 9}]}),
        "failed",
        "malformed",
    ),
    "outline/refused": (
        _structured(
            "NovelizeOutlineResult",
            {"episodes": [{**_TWO_EPISODES[0], "summary": _REFUSAL}, {**_TWO_EPISODES[1], "summary": _REFUSAL}]},
        ),
        "failed",
        "refused",
    ),
    "outline/source_changed": (
        _during_call(_drop_the_last_include, "구성안 호출 도중 사용자가 근거 구간을 뺀 선택을 승인했다"),
        "failed",
        "source_changed",
    ),
    **_call_failures("outline"),
    "outline/expired_during_call": (
        _during_call(_expire_the_job, "구성안 호출 도중 만료 정리가 돌았다"),
        "failed",
        "expired",
    ),
    # 장면 구성안
    "episode_outline/succeeded": (_as_is, "succeeded", None),
    "episode_outline/malformed": (
        _structured("NovelizeEpisodeOutlineResult", {"scenes": [_scene("시작", 1, 9)]}),
        "failed",
        "malformed",
    ),
    "episode_outline/refused": (
        _structured(
            "NovelizeEpisodeOutlineResult",
            {"scenes": [_scene("시작", 1, 1, summary=_REFUSAL), _scene("이어짐", 2, 3, summary=_REFUSAL)]},
        ),
        "failed",
        "refused",
    ),
    "episode_outline/source_changed": (
        _during_call(_drop_the_last_include, "장면 구성안 호출 도중 사용자가 그 화의 근거 구간을 뺀 선택을 승인했다"),
        "failed",
        "source_changed",
    ),
    **_call_failures("episode_outline"),
    # 구성 흐름 원고
    "manuscript/succeeded": (_as_is, "succeeded", None),
    "manuscript/malformed_more_than_one_episode": (_stream(_batch_output(_BODY, _BODY)), "failed", "malformed"),
    "manuscript/source_changed": (
        _during_call(_narrow_the_first_episode_basis, "원고 호출 도중 사용자가 그 화의 근거를 줄인 구성안을 승인했다"),
        "failed",
        "source_changed",
    ),
    **_call_failures("manuscript"),
}


# ── 기록 ─────────────────────────────────────────────────────────────────────
_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


def _norm(value: str, ids: dict[str, str]) -> str:
    """id 를 처음 나온 순서의 번호로 바꾼다."""
    return _UUID.sub(lambda m: ids.setdefault(m.group(0), f"<id{len(ids) + 1}>"), value)


# 경고를 모으는 로거. 하위 모듈(작업 실행·경계 제안 등)의 로거가 전파해 오므로 모듈을 옮겨도 같은 경고가 잡힌다.
_NOVELIZE_LOGGER = logging.getLogger("api.novelize")


class _NovelizeWarnings(logging.Handler):
    """소설화 패키지 로거에 올라온 WARNING 이상을 렌더된 글의 첫 `": "` 앞까지 모은다(로거 이름은 남기지 않는다)."""

    def __init__(self) -> None:
        super().__init__(logging.WARNING)
        self.lines: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.lines.append(record.getMessage().split(": ", 1)[0])


def _job_state(job: NovelJob) -> dict[str, Any]:
    return {
        "kind": job.kind,
        "status": job.status,
        "failureCode": job.failure_code,
        "model": job.model,
        "charged": job.charged_amount,
        "refunded": job.refunded_amount,
        "consumed": job.consumed_amount,
        "episodeTarget": job.episode_count_target,
        "hasResultText": job.result_text is not None,
        "hasInstruction": job.instruction is not None,
        "patchStates": None if job.block_edit is None else [p["state"] for p in job.block_edit["patches"]],
        "hasBatch": job.batch_id is not None,
        "hasChapter": job.chapter_id is not None,
        "hasResultRevision": job.result_revision_id is not None,
        "finished": job.finished_at is not None,
        "refundedAt": job.refunded_at is not None,
    }


async def _ledger_ids(db: AsyncSession, user_id: uuid.UUID) -> set[uuid.UUID]:
    return set((await db.scalars(sa.select(CloverLedger.id).where(CloverLedger.user_id == user_id))).all())


async def _money(ctx: _Ctx, before: set[uuid.UUID]) -> dict[str, Any]:
    """이 작업이 만든 원장 행(종류, 금액)과 그 차감들의 사용처."""
    db = ctx.db_session
    rows = (
        await db.execute(
            sa.select(CloverLedger.id, CloverLedger.kind, CloverLedger.amount)
            .where(CloverLedger.user_id == ctx.room.user_id)
            .order_by(CloverLedger.amount, CloverLedger.kind)
        )
    ).all()
    new = [row for row in rows if row.id not in before]
    usages = (
        await db.execute(
            sa.select(CloverSpendUsage.usage_kind, CloverSpendUsage.novel_id, CloverSpendUsage.chat_room_id)
            .where(CloverSpendUsage.spend_ledger_id.in_([row.id for row in new]))
            .order_by(CloverSpendUsage.usage_kind)
        )
    ).all()
    return {
        "ledger": [[row.kind, row.amount] for row in new],
        "usages": [[kind, novel_id == ctx.novel_id, room_id is not None] for kind, novel_id, room_id in usages],
    }


async def _output(ctx: _Ctx, title_before: str | None) -> dict[str, Any]:
    """소설에 남은 산출 행의 모양. 셋업이 만든 행도 함께 센다 — 칸끼리는 같은 셋업이라 차이가 이 작업의 몫이다."""
    db = ctx.db_session
    novel = await db.get_one(Novel, ctx.novel_id, populate_existing=True)
    chapter_rows = (
        await db.execute(
            sa.select(NovelChapter.id, NovelChapter.title, NovelChapter.summary)
            .where(NovelChapter.novel_id == ctx.novel_id)
            .order_by(NovelChapter.ordinal)
        )
    ).all()
    chapters = [row.id for row in chapter_rows]
    revisions = (
        await db.execute(
            sa.select(
                NovelChapter.ordinal,
                NovelChapterRevision.revision_no,
                NovelChapterRevision.source,
                NovelChapterRevision.body,
            )
            .join(NovelChapter, NovelChapter.id == NovelChapterRevision.chapter_id)
            .where(NovelChapter.novel_id == ctx.novel_id)
            .order_by(NovelChapter.ordinal, NovelChapterRevision.revision_no)
        )
    ).all()

    async def count(model: Any, *where: Any) -> int:
        return int(await db.scalar(sa.select(sa.func.count()).select_from(model).where(*where)) or 0)

    outlines = (
        await db.execute(
            sa.select(NovelOutline.revision, NovelOutline.source, NovelOutline.episodes)
            .where(NovelOutline.novel_id == ctx.novel_id)
            .order_by(NovelOutline.revision)
        )
    ).all()
    scene_outlines = (
        await db.execute(
            sa.select(NovelEpisodeOutline.revision, NovelEpisodeOutline.source, NovelEpisodeOutline.scenes)
            .where(NovelEpisodeOutline.novel_id == ctx.novel_id)
            .order_by(NovelEpisodeOutline.created_at, NovelEpisodeOutline.revision)
        )
    ).all()
    character_names = (
        await db.scalars(
            sa.select(NovelCharacter.name).where(NovelCharacter.novel_id == ctx.novel_id).order_by(NovelCharacter.name)
        )
    ).all()

    def paragraphs_digest(body: str) -> str:
        return hashlib.sha256(json.dumps(split_paragraphs(body), ensure_ascii=False).encode("utf-8")).hexdigest()[:16]

    def titles(items: list[dict[str, Any]]) -> list[list[Any]]:
        return [[item.get("title"), item.get("summary")] for item in items]

    title_changed = novel.title != title_before
    return {
        "batches": await count(NovelBatch, NovelBatch.novel_id == ctx.novel_id),
        "chapters": len(chapters),
        "chapterTitles": [[row.title, row.summary] for row in chapter_rows],
        "revisions": [
            [ordinal, number, source, paragraphs_digest(body)] for ordinal, number, source, body in revisions
        ],
        "sceneBlocks": await count(NovelSceneBlock, NovelSceneBlock.chapter_id.in_(chapters)),
        "characters": await count(NovelCharacter, NovelCharacter.novel_id == ctx.novel_id),
        "characterNames": list(character_names),
        "outlines": [[revision, source, titles(episodes)] for revision, source, episodes in outlines],
        "sceneOutlines": [[revision, source, titles(scenes)] for revision, source, scenes in scene_outlines],
        "writingLock": novel.writing_lock_source,
        "titleChanged": title_changed,
        "novelTitle": novel.title if title_changed else None,
    }


def test_recorded_cells_are_exactly_the_parametrized_cells() -> None:
    _assert_recorded_cases(FIXTURE_PATH, _CELLS, UPDATE_ENV)


def test_every_branch_has_cells() -> None:
    """칸 표의 갈래가 셋업 표의 갈래와 같다 — 셋업만 있고 칸이 없는 갈래가 조용히 빠지지 않게."""
    assert {cell.split("/", 1)[0] for cell in _CELLS} == set(_BRANCHES)


@pytest.mark.parametrize("cell", [pytest.param(cell, id=cell) for cell in _CELLS])
async def test_cell_matches_the_recorded_behavior(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    enqueued: list[uuid.UUID],
    cell: str,
) -> None:
    branch = _BRANCHES[cell.split("/", 1)[0]]
    arm, expected_status, expected_code = _CELLS[cell]
    setup_llm = _setup_llm()
    _override_llm_client(setup_llm)
    warnings = _NovelizeWarnings()
    try:
        ctx = await _base_ctx(db_client, db_session, monkeypatch, enqueued, setup_llm, turns=branch.turns)
        await branch.prepare(ctx)
        await arm(ctx)
        before = await _ledger_ids(db_session, ctx.room.user_id)
        title_before = (await db_session.get_one(Novel, ctx.novel_id, populate_existing=True)).title
        ctx.job_id = await branch.request(ctx)
        if ctx.before_run is not None:
            await ctx.before_run()
        _NOVELIZE_LOGGER.addHandler(warnings)
        try:
            if branch.chain:
                await runner.run_chain(ctx.factory, ctx.llm, ctx.job_id)
            else:
                await runner.run_job(ctx.factory, ctx.llm, ctx.job_id)
        finally:
            _NOVELIZE_LOGGER.removeHandler(warnings)
    finally:
        _clear_llm_override()

    for description, reached in ctx.witnesses:
        assert reached(), description
    job = await db_session.get_one(NovelJob, ctx.job_id, populate_existing=True)
    assert (job.status, job.failure_code) == (expected_status, expected_code)
    ids: dict[str, str] = {str(ctx.job_id): "<job>"}
    state: dict[str, Any] = {
        "job": _job_state(job),
        **await _money(ctx, before),
        "output": await _output(ctx, title_before),
        "calls": ctx.llm.calls,
        "warnings": [_norm(line, ids) for line in warnings.lines],
    }
    if branch.chain:
        children = (
            await db_session.scalars(
                sa.select(NovelJob)
                .where(NovelJob.parent_job_id == ctx.job_id)
                .order_by(NovelJob.start_message_created_at)
                .execution_options(populate_existing=True)
            )
        ).all()
        state["children"] = [_job_state(child) for child in children]
    _assert_characterization(FIXTURE_PATH, cell, state, UPDATE_ENV)
