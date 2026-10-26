"""측정 서버의 소설 프롬프트 덤프 — 소설 작업이 모델을 부르기 직전에 그 호출의 재렌더 입력을 한 줄로 남긴다.

덤프 경로 설정이 없으면(운영) 아무것도 쓰지 않고, 있으면 작업 하나마다 한 줄을 쓴다. 줄에는 렌더된 지시문·본문 대신 그 sha256 을
남기고, 다시 렌더할 입력(소설 세트 id·채널·원작 종류·등급 규칙 여부·슬롯 값 사전)을 남긴다 — 다음 단계의 리플레이가 덤프만으로
같은 바이트를 다시 만들 수 있어야 해서다. 여기서는 측정 대상인 세 채널(전체 구성안·장면 구성안·화 생성)을 구성 흐름 하나로 돌린다:
선택 승인 → 전체 구성안 작업 → 승인 → 장면 구성안 작업 → 승인 → 원고 작업.

작업은 라우트로 만들고(띄우는 함수를 기록 함수로 바꿔 끼운다) 실행 함수를 직접 기다린다. 세션 팩토리는 테스트 커넥션 하나에
SAVEPOINT 로 붙으므로 heartbeat 주기를 크게 늘려 작업 본문과 부딪히지 않게 한다."""

import hashlib
import json
import logging
import re
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx
import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from api.core import clover
from api.core.config import settings
from api.db.models import ChatMessage
from api.db.models.novel import NovelJob
from api.db.models.prompt import PromptSection, PromptSet
from api.llm.client import LLMCallContext, LLMClient, LLMClientError, T
from api.novelize import router as novelize_router
from api.novelize import runner
from api.novelize.prompts import _render
from factories import (
    Room,
    _batch_output,
    _clear_llm_override,
    _novel_setup,
    _override_llm_client,
    _room_messages,
    _set_model_price,
)

pytestmark = pytest.mark.usefixtures("novel_prices_for_flow_tests")

# 합성 문안. 화 본문은 최소 길이(200자)를 넘는다.
_BODY = "비가 내리는 저녁이었다. 서진은 가방을 내려놓고 창가에 섰다.\n\n" + "도윤이 잔을 밀어 주었다. " * 20
# 원문 한 줄에 심는 표지 — 덤프의 슬롯 값에는 실리고 로그에는 실리지 않아야 한다.
_MARKER = "덤프표지바다별모래시계"
# 6턴 방의 선택 — include 오프닝~2턴 · context 3턴 · 고르지 않은 4턴 · include 5~6턴.
_SECTIONS = (("include", 0, 4), ("context", 5, 6), ("include", 9, 12))
_TWO_EPISODES = [
    {"title": "첫 만남", "summary": "둘이 처음 만났다.", "goal": "서로를 궁금해한다.", "start_turn": 1, "end_turn": 2},
    {"title": "다시 만남", "summary": "둘이 다시 만났다.", "goal": "약속을 남긴다.", "start_turn": 3, "end_turn": 5},
]
_TURN = re.compile(r"^\[턴 (\d+)\]", re.MULTILINE)
_OUTLINE_COST = 11
_SCENES_COST = 7
_EPISODE_COST = 40

# 덤프 한 줄의 칸 — 다음 단계의 리플레이가 읽는 계약이다.
_RECORD_KEYS = {
    "jobId",
    "branch",
    "callSite",
    "jobModel",
    "callModel",
    "novelSetId",
    "channel",
    "scope",
    "withRating",
    "values",
    "systemSha256",
    "promptSha256",
    "schema",
}


def _dump_lines(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _dump_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _entries(directory: Path) -> list[Path]:
    return list(directory.iterdir())


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _scene(title: str, start: int, end: int) -> dict[str, Any]:
    return {
        "title": title,
        "summary": f"{title} 장면에서 일이 일어났다.",
        "purpose": f"{title} 뒤에 무엇이 달라진다.",
        "characters": ["서진", "도윤"],
        "flashback": False,
        "start_turn": start,
        "end_turn": end,
    }


class _DumpLLM(LLMClient):
    """소설 작업의 호출을 받는 가짜. 경계 제안은 실패시키고, 나머지 호출은 (호출 위치, 스키마 이름, 받은 지시문, 받은 본문)을 적는다."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str | None, str, str]] = []

    async def generate(
        self,
        prompt: str,
        system_instruction: str | None = None,
        stop_sequences: list[str] | None = None,
        *,
        usage: LLMCallContext,
    ) -> AsyncIterator[str]:
        self.calls.append((usage.call_site, None, system_instruction or "", prompt))
        yield _batch_output(_BODY)

    async def generate_structured(
        self, prompt: str, response_schema: Any, images: Any = None, *, usage: LLMCallContext
    ) -> Any:
        raise AssertionError("소설 작업은 지시문 없는 구조화 호출을 쓰지 않는다")

    async def generate_structured_with_instruction(
        self, prompt: str, response_schema: type[T], *, system_instruction: str, usage: LLMCallContext
    ) -> T:
        if usage.call_site == "novelize_boundary":
            raise LLMClientError("경계 제안 실패")
        name = response_schema.__name__
        self.calls.append((usage.call_site, name, system_instruction, prompt))
        if name == "NovelizeOutlineResult":
            return response_schema.model_validate({"episodes": _TWO_EPISODES})
        if name == "NovelizeEpisodeOutlineResult":
            last = max(int(n) for n in _TURN.findall(prompt))
            scenes = [_scene("시작", 1, 1), _scene("이어짐", 2, last)] if last > 1 else [_scene("시작", 1, 1)]
            return response_schema.model_validate({"scenes": scenes})
        raise AssertionError(f"응답을 정하지 않은 스키마: {name}")


@pytest.fixture(autouse=True)
def _flow_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "novelize_heartbeat_interval_seconds", 3600)
    monkeypatch.setattr(settings, "novelize_outline_flow_enabled", True)
    _set_model_price(monkeypatch, "gemini", novel_outline=_OUTLINE_COST, novel_episode_outline=_SCENES_COST)


@pytest.fixture
def enqueued(monkeypatch: pytest.MonkeyPatch) -> list[uuid.UUID]:
    """라우트가 띄운 작업 id. 실제로 돌리지는 않는다 — 시험이 직접 실행 함수에 넘긴다."""
    seen: list[uuid.UUID] = []

    async def record(_factory: Any, _llm: Any, job_id: uuid.UUID) -> None:
        seen.append(job_id)

    monkeypatch.setattr(novelize_router, "enqueue_job", record)
    return seen


def _factory(db_session: AsyncSession) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(bind=db_session.bind, expire_on_commit=False, join_transaction_mode="create_savepoint")


def _accepted(response: httpx.Response, enqueued: list[uuid.UUID]) -> uuid.UUID:
    assert response.status_code == 202, response.text
    return enqueued[-1]


async def _run(db_session: AsyncSession, llm: LLMClient, job_id: uuid.UUID) -> NovelJob:
    await runner.run_job(_factory(db_session), llm, job_id)
    job = await db_session.get_one(NovelJob, job_id, populate_existing=True)
    assert job.status == "succeeded", job.failure_code
    return job


async def _select(db_client: httpx.AsyncClient, novel_id: uuid.UUID, ms: list[ChatMessage]) -> None:
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
                for mode, a, b in _SECTIONS
            ],
        },
    )
    assert saved.status_code == 200, saved.text
    approved = await db_client.post(f"{base}/approve", json={"revision": saved.json()["draft"]["revision"]})
    assert approved.status_code == 200, approved.text


async def _three_jobs(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    enqueued: list[uuid.UUID],
    llm: _DumpLLM,
) -> tuple[Room, list[uuid.UUID]]:
    """전체 구성안 → 장면 구성안 → 원고 작업을 차례로 돌리고 (방, 세 작업 id) 를 돌려준다. 원문 첫 모델 응답에 표지를 심는다."""
    room, novel_id = await _novel_setup(db_client, db_session, monkeypatch, turns=6)
    await clover.grant(db_session, user_id=room.user_id, amount=1000, kind="admin_grant")
    ms = await _room_messages(db_session, room.room_id)
    opening = ms[0]
    opening.content = f"{opening.content} {_MARKER}"
    await db_session.commit()
    await _select(db_client, novel_id, ms)

    outline_job = _accepted(
        await db_client.post(f"/novels/{novel_id}/outline", json={"model": "gemini", "expectedCost": _OUTLINE_COST}),
        enqueued,
    )
    await _run(db_session, llm, outline_job)
    state = (await db_client.get(f"/novels/{novel_id}/outline")).json()
    approved = await db_client.post(
        f"/novels/{novel_id}/outline/approve", json={"revision": state["draft"]["revision"]}
    )
    assert approved.status_code == 200, approved.text
    key = approved.json()["approved"]["episodes"][0]["key"]

    scenes_url = f"/novels/{novel_id}/outline/episodes/{key}/scenes"
    scenes_job = _accepted(
        await db_client.post(scenes_url, json={"model": "gemini", "expectedCost": _SCENES_COST}), enqueued
    )
    await _run(db_session, llm, scenes_job)
    state = (await db_client.get(scenes_url)).json()
    approved = await db_client.post(f"{scenes_url}/approve", json={"revision": state["draft"]["revision"]})
    assert approved.status_code == 200, approved.text

    manuscript_job = _accepted(
        await db_client.post(
            f"/novels/{novel_id}/outline/episodes/{key}/chapter",
            json={"model": "gemini", "expectedCost": _EPISODE_COST},
        ),
        enqueued,
    )
    await _run(db_session, llm, manuscript_job)
    return room, [outline_job, scenes_job, manuscript_job]


async def _dumped_run(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    enqueued: list[uuid.UUID],
    path: Path,
) -> tuple[_DumpLLM, list[uuid.UUID], list[dict[str, Any]]]:
    monkeypatch.setattr(settings, "novel_prompt_dump_path", str(path))
    llm = _DumpLLM()
    _override_llm_client(llm)
    try:
        _, jobs = await _three_jobs(db_client, db_session, monkeypatch, enqueued, llm)
    finally:
        _clear_llm_override()
    return llm, jobs, _dump_lines(path)


async def test_without_a_dump_path_nothing_is_written_and_the_calls_are_the_same(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    enqueued: list[uuid.UUID],
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(settings, "novel_prompt_dump_path", None)
    monkeypatch.chdir(tmp_path)
    llm = _DumpLLM()
    _override_llm_client(llm)
    try:
        await _three_jobs(db_client, db_session, monkeypatch, enqueued, llm)
    finally:
        _clear_llm_override()

    assert _entries(tmp_path) == []
    assert [(site, schema) for site, schema, _, _ in llm.calls] == [
        ("novelize_outline", "NovelizeOutlineResult"),
        ("novelize_episode_outline", "NovelizeEpisodeOutlineResult"),
        ("novelize_chapter", None),
    ]


async def test_with_a_dump_path_each_job_writes_one_line_with_a_fixed_set_of_fields(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    enqueued: list[uuid.UUID],
    tmp_path: Path,
) -> None:
    llm, jobs, records = await _dumped_run(db_client, db_session, monkeypatch, enqueued, tmp_path / "novel.jsonl")

    assert len(llm.calls) == 3
    assert [set(record) for record in records] == [_RECORD_KEYS] * 3
    assert [record["jobId"] for record in records] == [str(job) for job in jobs]
    assert [(r["branch"], r["callSite"], r["channel"], r["schema"]) for r in records] == [
        ("outline", "novelize_outline", "novelize_outline", "NovelizeOutlineResult"),
        ("episode_outline", "novelize_episode_outline", "novelize_episode_outline", "NovelizeEpisodeOutlineResult"),
        ("manuscript", "novelize_chapter", "novelize_chapter", None),
    ]
    assert {(r["jobModel"], r["scope"], r["withRating"]) for r in records} == {("gemini", "character", True)}
    assert all(isinstance(r["callModel"], str) and r["callModel"] for r in records)
    # 덤프의 sha 는 가짜 모델이 실제로 받은 바이트의 sha 다.
    assert [(r["systemSha256"], r["promptSha256"]) for r in records] == [
        (_sha(system), _sha(prompt)) for _, _, system, prompt in llm.calls
    ]
    active = await db_session.scalar(
        sa.select(PromptSet)
        .where(PromptSet.status == "published", PromptSet.lane == "novel", PromptSet.model == "gemini")
        .order_by(PromptSet.published_at.desc())
        .limit(1)
    )
    assert active is not None
    assert {r["novelSetId"] for r in records} == {str(active.id)}


async def test_the_dumped_values_and_set_id_render_the_same_bytes_again(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    enqueued: list[uuid.UUID],
    tmp_path: Path,
) -> None:
    llm, _, records = await _dumped_run(db_client, db_session, monkeypatch, enqueued, tmp_path / "novel.jsonl")

    for record, (_, _, system, prompt) in zip(records, llm.calls, strict=True):
        sections = list(
            (
                await db_session.scalars(
                    sa.select(PromptSection).where(PromptSection.prompt_set_id == uuid.UUID(record["novelSetId"]))
                )
            ).all()
        )
        again = _render(
            sections,
            channel=record["channel"],
            is_story_chat=record["scope"] == "story",
            values=record["values"],
            with_rating=record["withRating"],
        )
        # 문안 본문이 시험 출력에 실리지 않게 sha 로만 견준다.
        assert (_sha(again.system_instruction), _sha(again.prompt)) == (
            record["systemSha256"],
            record["promptSha256"],
        )
        assert (_sha(again.system_instruction), _sha(again.prompt)) == (_sha(system), _sha(prompt))


async def test_the_source_text_reaches_the_dump_but_not_the_logs(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    enqueued: list[uuid.UUID],
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    path = tmp_path / "novel.jsonl"
    with caplog.at_level(logging.DEBUG):
        llm, _, records = await _dumped_run(db_client, db_session, monkeypatch, enqueued, path)

    assert all(_MARKER in prompt for _, _, _, prompt in llm.calls)
    assert all(_MARKER in json.dumps(r["values"], ensure_ascii=False) for r in records)
    assert _MARKER in _dump_text(path)
    assert not any(_MARKER in record.getMessage() for record in caplog.records)
    assert _MARKER not in caplog.text
