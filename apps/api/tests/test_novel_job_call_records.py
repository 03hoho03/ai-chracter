"""소설 작업 행의 모델 호출 기록(`novel_jobs.llm_calls`) — 작업이 부른 호출마다 원소 하나가 결과 저장이나 실패·환불과 같은
트랜잭션에 남는다.

원소는 공급자 구현이 남기는 사용량 칸(`CallUsage.as_record`)에 소설 쪽이 구현·걸린 시간·소설 세트 id·단계·배정 출처·호출 실패
사유를 덧붙인 꼴이다. 사용량 없이 끝난 호출(안전 차단·전송 오류·시간 상한 취소)도 원소가 되고 그때는 토큰 칸이 없다.

가짜 모델은 실제 공급자 구현과 같은 자리에서 `collect_usage` 를 부른다 — 스트림은 다 흘린 뒤, 구조화 호출은 응답 판정 앞. 칸은
deferred 라 ORM 객체로 읽으면 비동기 세션에서 지연 로드가 일어나므로 늘 칸만 골라 SELECT 한다."""

import asyncio
import json
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from api.chat.prompt_builder import load_active_prompt_set
from api.core import clover
from api.core.config import settings
from api.db.models import ChatMessage, ChatRoom, Novel, NovelChapter, NovelChapterRevision, NovelJob
from api.llm.client import (
    LLMCallContext,
    LLMClient,
    LLMClientError,
    LLMPolicyViolationError,
    LLMRateLimitError,
    LLMTruncatedError,
    T,
    collect_usage,
    structured_model,
)
from api.llm.routing import resolve_backend
from api.main import app
from api.novelize import billing, runner
from api.novelize import router as novelize_router
from factories import (
    _add_chapter,
    _batch_output,
    _clear_llm_override,
    _edited_recheck_bundle,
    _make_user_with_clover_lot,
    _novel_setup,
    _open_room,
    _override_llm_client,
    _queue_job,
    _room_messages,
    _set_model_price,
)

pytestmark = pytest.mark.usefixtures("novel_prices_for_flow_tests")

_BODY = "비가 내리는 저녁이었다. 서진은 가방을 내려놓고 창가에 섰다.\n\n" + "도윤이 잔을 밀어 주었다. " * 20
_PARAGRAPHS = ["첫 문단이다.", "둘째 문단이다.", "셋째 문단이다.", "넷째 문단이다."]
_REPORTED_MODEL = "fixture-reported-model"
# 공급자가 보고한 사용량 — 합성 값이다. 캐시 쓰기·생각 토큰은 보고하지 않은 칸(None)으로 둔다.
_META = SimpleNamespace(
    prompt_token_count=1200,
    cached_content_token_count=200,
    cache_write_token_count=None,
    candidates_token_count=300,
    thoughts_token_count=None,
)
_USAGE_KEYS = {
    "callSite": "",
    "model": _REPORTED_MODEL,
    "promptTokens": 1200,
    "cachedTokens": 200,
    "cacheWriteTokens": None,
    "outputTokens": 300,
    "thoughtsTokens": None,
}
_ADDED_KEYS = {"backend", "durationMs", "promptSetId", "stage", "routeSource", "failure"}
_ANSWERS: dict[str, dict[str, Any]] = {
    "NovelizeReviseResult": {"paragraphs": ["고친 둘째 문단이다."]},
    "NovelizeRecheckResult": {"separable": False, "reason": "남은 수정안이 고치기 전 이름을 쓴다."},
    "NovelizeBoundaryResult": {"end_turn": 1, "reason": "장면이 매듭지어진다."},
    "NovelizeOutlineResult": {
        "episodes": [
            {"title": "첫 만남", "summary": "둘이 처음 만났다.", "goal": "서로를 궁금해한다.", "start_turn": 1, "end_turn": 2},
            {"title": "다시 만남", "summary": "둘이 다시 만났다.", "goal": "약속을 남긴다.", "start_turn": 3, "end_turn": 5},
        ]
    },
}


class _UsageLLM(LLMClient):
    """사용량을 남기는 소설 페이크. `before` 는 사용량을 남기기 전에(공급자가 응답 전에 실패한 호출), `after` 는 남긴 뒤에(잘림·빈
    본문처럼 공급자가 기록한 뒤 올리는 실패) 낸다. `during` 은 모델을 부르는 순간 실행할 일이다. 화 생성 스트림은 `chunks` 를 흘린다."""

    def __init__(
        self,
        *,
        chunks: list[str] | None = None,
        before: Exception | None = None,
        after: Exception | None = None,
        during: Callable[[], Awaitable[None]] | None = None,
        answers: dict[str, dict[str, Any]] | None = None,
    ) -> None:
        self.chunks = chunks if chunks is not None else [_batch_output(_BODY)]
        self.before = before
        self.after = after
        self.during = during
        self.answers = answers if answers is not None else _ANSWERS
        self.calls: list[LLMCallContext] = []

    async def generate(
        self,
        prompt: str,
        system_instruction: str | None = None,
        stop_sequences: list[str] | None = None,
        *,
        usage: LLMCallContext,
    ) -> AsyncIterator[str]:
        self.calls.append(usage)
        if self.during is not None:
            await self.during()
        if self.before is not None:
            raise self.before
        for chunk in self.chunks:
            yield chunk
        collect_usage(usage, _REPORTED_MODEL, _META)
        if self.after is not None:
            raise self.after

    async def generate_structured(
        self, prompt: str, response_schema: Any, images: Any = None, *, usage: LLMCallContext
    ) -> Any:
        raise AssertionError("소설화는 지시문 없는 구조화 호출을 쓰지 않는다")

    async def generate_structured_with_instruction(
        self, prompt: str, response_schema: type[T], *, system_instruction: str, usage: LLMCallContext
    ) -> T:
        self.calls.append(usage)
        if self.during is not None:
            await self.during()
        if self.before is not None:
            raise self.before
        collect_usage(usage, _REPORTED_MODEL, _META)
        if self.after is not None:
            raise self.after
        return response_schema.model_validate(self.answers[response_schema.__name__])


@pytest.fixture(autouse=True)
def _slow_heartbeat(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "novelize_heartbeat_interval_seconds", 3600)
    monkeypatch.setattr(settings, "novelize_heartbeat_expiry_seconds", 60)


@pytest.fixture
def llm() -> Iterator[_UsageLLM]:
    """라우트가 받는 모델 클라이언트도 같은 가짜로 갈아 끼운다(재검사·경계 제안은 라우트 안에서 부른다)."""
    fake = _UsageLLM()
    _override_llm_client(fake)
    yield fake
    _clear_llm_override()


def _factory(db_session: AsyncSession) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(bind=db_session.bind, expire_on_commit=False, join_transaction_mode="create_savepoint")


async def _calls(db: AsyncSession, job_id: uuid.UUID) -> list[dict[str, Any]]:
    calls = await db.scalar(sa.select(NovelJob.llm_calls).where(NovelJob.id == job_id))
    assert calls is not None
    return list(calls)


async def _status(db: AsyncSession, job_id: uuid.UUID) -> tuple[str, str | None]:
    row = (await db.execute(sa.select(NovelJob.status, NovelJob.failure_code).where(NovelJob.id == job_id))).one()
    return row[0], row[1]


async def _novel_set_id(db: AsyncSession) -> str:
    prompt_set, _ = await load_active_prompt_set(db, lane="novel", model="gemini")
    return str(prompt_set.id)


def _sent_model(call_site: Any) -> str:
    """사용량 없는 실패 원소가 적을 모델 id — 요청에 실은 id 다(라우터 해석 + Gemini 는 클라이언트가 고르는 소설화 모델)."""
    backend, sent = resolve_backend(call_site, "gemini")
    return structured_model(call_site, sent) if backend == "gemini" else sent


def _assert_shape(record: dict[str, Any], *, with_usage: bool) -> None:
    expected = (set(_USAGE_KEYS) if with_usage else {"callSite", "model"}) | _ADDED_KEYS
    assert set(record) == expected
    assert isinstance(record["durationMs"], int) and record["durationMs"] >= 0


# ── 준비 ──────────────────────────────────────────────────────────────────
async def _novel(db_client: httpx.AsyncClient, db_session: AsyncSession) -> tuple[Novel, list[ChatMessage], Any]:
    owner = await _make_user_with_clover_lot(db_session, clover_balance=200)
    room = await _open_room(db_client, db_session, turns=3, lane="character", user=owner)
    chat_room = await db_session.get_one(ChatRoom, room.room_id)
    novel = Novel(
        user_id=owner.id,
        chat_room_id=room.room_id,
        content_id=chat_room.content_id,
        content_type="character",
        content_title="원작",
        character_name="캐릭터",
        protagonist_name="서진",
    )
    db_session.add(novel)
    await db_session.commit()
    return novel, await _room_messages(db_session, room.room_id), room


async def _ready_chapter_job(db_client: httpx.AsyncClient, db_session: AsyncSession) -> tuple[Novel, NovelJob]:
    novel, messages, room = await _novel(db_client, db_session)
    return novel, await _queue_job(db_session, novel.id, messages[0], room.turns[1][1])


async def _current(db: AsyncSession, chapter_id: uuid.UUID) -> NovelChapterRevision:
    revision = await db.scalar(
        sa.select(NovelChapterRevision)
        .where(NovelChapterRevision.chapter_id == chapter_id)
        .order_by(NovelChapterRevision.revision_no.desc())
        .limit(1)
        .execution_options(populate_existing=True)
    )
    assert revision is not None
    return revision


async def _paragraph_edit_job(db_client: httpx.AsyncClient, db_session: AsyncSession) -> NovelJob:
    novel, messages, room = await _novel(db_client, db_session)
    chapter: NovelChapter = await _add_chapter(
        db_session, novel.id, room, messages[0], room.turns[1][1], body="\n\n".join(_PARAGRAPHS)
    )
    base = await _current(db_session, chapter.id)
    job = NovelJob(
        novel_id=novel.id,
        user_id=novel.user_id,
        kind="ai_edit",
        chapter_id=chapter.id,
        base_revision_id=base.id,
        paragraph_start=1,
        paragraph_end=1,
        instruction="더 쓸쓸하게",
    )
    return await billing.create_charged_job(db_session, job=job, expected_cost=20, now=datetime.now(UTC))


# ── 성공 경로 ───────────────────────────────────────────────────────────────
async def test_a_chapter_job_records_its_call_with_the_reported_usage_when_it_saves(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """화 생성은 스트림 호출 하나를 원소 하나로 남긴다 — 공급자가 보고한 사용량 칸 그대로에 구현·걸린 시간·소설 세트 id·단계(작업
    갈래)를 덧붙인다. 화 생성은 배정 표를 읽지 않아 배정 출처가 비고, 호출이 정상 종료해 실패 사유도 빈다. 빨강 조건: 칸이 없거나,
    성공 저장이 기록을 싣지 않아 `[]` 로 남거나, 공급자 칸 이름을 바꿔 턴 기록과 모양이 갈린다."""
    _novel, job = await _ready_chapter_job(db_client, db_session)

    await runner.run_job(_factory(db_session), _UsageLLM(), job.id)

    assert await _status(db_session, job.id) == ("succeeded", None)
    (record,) = await _calls(db_session, job.id)
    _assert_shape(record, with_usage=True)
    assert {key: record[key] for key in _USAGE_KEYS} == {**_USAGE_KEYS, "callSite": "novelize_chapter"}
    assert (record["backend"], record["stage"], record["routeSource"], record["failure"]) == (
        "gemini",
        "legacy_generate",
        None,
        None,
    )
    assert record["promptSetId"] == await _novel_set_id(db_session)


async def test_a_paragraph_edit_records_its_call_and_the_route_source_of_its_stage(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """문단 수정은 배정 표의 문단 수정 칸을 읽으므로 그 해석의 출처를 싣는다 — 빈 표면 env 규칙이다. 빨강 조건: 구조화 호출 갈래가
    기록을 싣지 않거나, 배정 출처를 버린다."""
    job = await _paragraph_edit_job(db_client, db_session)

    await runner.run_job(_factory(db_session), _UsageLLM(), job.id)

    assert await _status(db_session, job.id) == ("succeeded", None)
    (record,) = await _calls(db_session, job.id)
    _assert_shape(record, with_usage=True)
    assert (record["callSite"], record["stage"], record["routeSource"], record["failure"]) == (
        "novelize_revise",
        "paragraph_edit",
        "env",
        None,
    )


async def _approve_selection(db_client: httpx.AsyncClient, novel_id: uuid.UUID, ms: list[ChatMessage]) -> None:
    """구성안 원문 선택을 하나 저장하고 승인한다 — include 오프닝·1·2턴과 5·6턴, 그 사이 맥락."""
    base = f"/novels/{novel_id}/source-selection"
    shown = (await db_client.get(base)).json()["proposal"]
    sections = (("include", 0, 4), ("context", 5, 6), ("include", 9, 12))
    saved = await db_client.put(
        f"{base}/draft",
        json={
            "baseRevision": None,
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


async def test_an_outline_job_records_its_call_in_the_saving_transaction(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, llm: _UsageLLM
) -> None:
    """전체 구성안도 같은 자리에서 원소 하나를 남긴다(단계 `outline`). 빨강 조건: 구성안 저장 함수가 기록을 싣지 않는다."""
    monkeypatch.setattr(settings, "novelize_outline_flow_enabled", True)
    _set_model_price(monkeypatch, "gemini", novel_outline=11)
    started: list[uuid.UUID] = []

    async def enqueue(_factory: Any, _llm: Any, job_id: uuid.UUID) -> None:
        started.append(job_id)

    monkeypatch.setattr(novelize_router, "enqueue_job", enqueue)
    room, novel_id = await _novel_setup(db_client, db_session, monkeypatch, turns=6)
    await _approve_selection(db_client, novel_id, await _room_messages(db_session, room.room_id))
    requested = await db_client.post(f"/novels/{novel_id}/outline", json={"model": "gemini", "expectedCost": 11})
    assert requested.status_code == 202, requested.text

    await runner.run_job(_factory(db_session), llm, started[-1])

    assert await _status(db_session, started[-1]) == ("succeeded", None)
    (record,) = await _calls(db_session, started[-1])
    _assert_shape(record, with_usage=True)
    assert (record["callSite"], record["stage"], record["failure"]) == ("novelize_outline", "outline", None)


# ── 실패 경로 ───────────────────────────────────────────────────────────────
async def test_a_failure_after_the_provider_reported_usage_keeps_the_usage_and_names_the_failure(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """잘림은 공급자가 사용량을 기록한 뒤 올린다 — 원소에 토큰이 남고 호출 실패 사유가 붙으며, 실패·환불 전이와 같이 쓰인다. 빨강
    조건: 실패 경로가 기록을 버려 과금된 토큰이 원가에서 빠진다."""
    _novel, job = await _ready_chapter_job(db_client, db_session)

    await runner.run_job(_factory(db_session), _UsageLLM(after=LLMTruncatedError("잘림")), job.id)

    assert await _status(db_session, job.id) == ("failed", "truncated")
    (record,) = await _calls(db_session, job.id)
    _assert_shape(record, with_usage=True)
    assert (record["promptTokens"], record["failure"]) == (1200, "truncated")


@pytest.mark.parametrize(
    ("error", "job_code", "failure"),
    [
        pytest.param(LLMPolicyViolationError("차단"), "blocked", "blocked", id="blocked"),
        pytest.param(LLMClientError("전송 오류"), "llm_error", "llm_error", id="transport"),
        pytest.param(LLMRateLimitError("쿼터"), "llm_error", "rate_limited", id="rate-limited"),
    ],
)
async def test_a_call_that_ends_without_usage_is_still_recorded_with_the_model_it_was_sent_to(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    error: Exception,
    job_code: str,
    failure: str,
) -> None:
    """공급자가 사용량을 남기기 전에 끝난 호출도 원소다 — 토큰 칸 없이 호출 위치와 요청에 실은 모델 id, 실패 사유만 갖는다.
    쿼터 소진은 작업 실패 사유로는 호출 실패지만 원소에서는 따로 가른다. 빨강 조건: 사용량이 없다고 원소를 건너뛰어 실패한 호출
    수가 원가 보고에서 사라지거나, 모델 칸이 비어 어느 모델의 실패인지 모른다."""
    _novel, job = await _ready_chapter_job(db_client, db_session)

    await runner.run_job(_factory(db_session), _UsageLLM(before=error), job.id)

    assert await _status(db_session, job.id) == ("failed", job_code)
    (record,) = await _calls(db_session, job.id)
    _assert_shape(record, with_usage=False)
    assert (record["callSite"], record["model"], record["backend"], record["failure"]) == (
        "novelize_chapter",
        _sent_model("novelize_chapter"),
        "gemini",
        failure,
    )


async def test_a_judgment_failure_after_a_finished_call_records_the_call_as_successful(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """호출은 정상 종료했고 소설 쪽 판정(형식)이 실패했으면 원소의 실패 사유는 비고, 작업 행의 실패 사유가 그 판정을 담는다. 빨강
    조건: 호출 뒤 판정 실패를 호출 실패로 적어 공급자 쪽 실패율이 부풀거나, 기록을 버린다."""
    _novel, job = await _ready_chapter_job(db_client, db_session)

    await runner.run_job(_factory(db_session), _UsageLLM(chunks=["===1화===\n" + _BODY]), job.id)

    assert await _status(db_session, job.id) == ("failed", "malformed")
    (record,) = await _calls(db_session, job.id)
    _assert_shape(record, with_usage=True)
    assert record["failure"] is None


async def test_a_call_cancelled_by_the_job_time_limit_is_recorded_without_usage(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """작업 시간 상한이 진행 중 호출을 취소하면 그 호출은 사용량 없이 `cancelled` 로 남고, 시간 초과 환불과 같이 쓰인다. 상한은
    입력 조립이 끝난 뒤 모델 호출 중에 걸리도록 여유를 둔다. 빨강 조건: 취소(`CancelledError`)를 놓쳐 원소가 빠진다."""
    monkeypatch.setattr(settings, "novelize_job_timeout_seconds", 2)
    _novel, job = await _ready_chapter_job(db_client, db_session)

    await runner.run_job(_factory(db_session), _UsageLLM(during=lambda: asyncio.sleep(10)), job.id)

    assert await _status(db_session, job.id) == ("failed", "timeout")
    (record,) = await _calls(db_session, job.id)
    _assert_shape(record, with_usage=False)
    assert record["failure"] == "cancelled"


async def test_the_record_is_written_by_the_refund_transaction_and_rolls_back_with_it(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """환불 함수가 받은 기록은 실패 전이와 같은 문장으로 쓰인다 — 그 트랜잭션이 롤백되면 기록도 없고 작업은 진행 중으로 남으며,
    커밋되면 둘 다 남는다. 빨강 조건: 기록을 따로 커밋해 환불이 없던 일이 됐는데 기록만 남는다(다시 환불하면 두 번 쌓인다)."""
    _novel, job = await _ready_chapter_job(db_client, db_session)
    # 롤백이 세션의 객체를 만료시키므로 id 를 먼저 꺼내 둔다 — 만료된 속성을 읽으면 비동기 세션 밖 지연 적재가 된다.
    job_id = job.id
    element = {"callSite": "novelize_chapter", "model": "fixture-model", "failure": "llm_error"}

    nested = await db_session.begin_nested()
    await billing.refund_job(db_session, job_id=job_id, failure_code="llm_error", llm_calls=[element])
    await nested.rollback()
    rolled_back = (await _status(db_session, job_id), await _calls(db_session, job_id))

    await billing.refund_job(db_session, job_id=job_id, failure_code="llm_error", llm_calls=[element])
    await db_session.commit()

    assert rolled_back == (("queued", None), [])
    assert (await _status(db_session, job_id), await _calls(db_session, job_id)) == (("failed", "llm_error"), [element])


async def test_expiry_and_novel_deletion_refunds_leave_the_record_empty(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """만료 정리와 소설 삭제 환불은 호출 목록을 모른다(다른 프로세스·요청이다) — 칸을 건드리지 않아 `[]` 그대로다. 빨강 조건: 두
    경로가 칸을 비우지 않은 값이나 NULL 로 덮는다."""
    novel, job = await _ready_chapter_job(db_client, db_session)
    await db_session.execute(
        sa.update(NovelJob).where(NovelJob.id == job.id).values(heartbeat_at=sa.func.now() - timedelta(hours=1))
    )
    expired = await runner.expire_stale_jobs(db_session, novel_id=novel.id)
    await db_session.commit()

    other, other_job = await _ready_chapter_job(db_client, db_session)
    refunded = await billing.refund_active_jobs(db_session, novel_id=other.id, failure_code="internal")
    await db_session.commit()

    assert (expired, refunded) == (1, 40)
    assert (await _status(db_session, job.id), await _calls(db_session, job.id)) == (("failed", "expired"), [])
    assert (await _status(db_session, other_job.id), await _calls(db_session, other_job.id)) == (
        ("failed", "internal"),
        [],
    )


# ── 연쇄 생성 ───────────────────────────────────────────────────────────────
async def test_a_chain_records_the_boundary_call_on_the_parent_and_each_chapter_call_on_its_child(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, llm: _UsageLLM
) -> None:
    """연쇄 부모는 직접 부른 경계 제안을 자기 행에, 자식은 화 생성을 자기 행에 남긴다 — 같은 호출이 두 행에 겹쳐 들지 않는다.
    빨강 조건: 경계 호출이 어느 행에도 남지 않거나, 부모가 자식의 호출까지 모아 합계에서 두 번 센다."""
    room, novel_id = await _novel_setup(db_client, db_session, monkeypatch)
    await clover.grant(db_session, user_id=room.user_id, amount=2000, kind="admin_grant")
    await db_session.commit()
    started: list[uuid.UUID] = []

    async def record(_factory: Any, _llm: Any, job_id: uuid.UUID) -> None:
        started.append(job_id)

    monkeypatch.setattr(novelize_router, "enqueue_chain_job", record)
    estimate = await db_client.get(f"/novels/{novel_id}/chain-estimate")
    assert estimate.status_code == 200, estimate.text
    (option,) = [o for o in estimate.json()["options"] if o["model"] == "gemini"]
    created = await db_client.post(
        f"/novels/{novel_id}/chain",
        json={"model": "gemini", "expectedCost": option["cost"] // option["batchCount"], "maxBatches": 1},
    )
    assert created.status_code == 202, created.text

    await runner.run_chain(_factory(db_session), llm, started[0])

    (parent_call,) = await _calls(db_session, started[0])
    child_id = await db_session.scalar(sa.select(NovelJob.id).where(NovelJob.parent_job_id == started[0]))
    assert child_id is not None
    (child_call,) = await _calls(db_session, child_id)
    assert await _status(db_session, started[0]) == ("succeeded", None)
    _assert_shape(parent_call, with_usage=True)
    _assert_shape(child_call, with_usage=True)
    assert (parent_call["callSite"], parent_call["stage"], parent_call["routeSource"]) == (
        "novelize_boundary",
        "boundary",
        "env",
    )
    assert (child_call["callSite"], child_call["stage"]) == ("novelize_chapter", "chain_child")


# ── 묶음 재검사(동기 요청) ───────────────────────────────────────────────────────
async def test_a_recheck_appends_its_call_to_the_job_only_when_the_verdict_is_written(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, llm: _UsageLLM
) -> None:
    """재검사는 이미 끝난 작업 행에 원소를 덧붙인다 — 판정을 쓰는 트랜잭션에서만(따로 적용할 수 없다는 판정도 쓴 판정이다). 호출
    실패(503)는 작업 행을 잡지 않으므로 남기지 않는다. 빨강 조건: 재검사가 기록을 덮어써 작업 호출이 사라지거나, 503 갈래가 따로
    트랜잭션을 열어 기록한다."""
    job_id, url, _novel = await _edited_recheck_bundle(db_client, db_session, monkeypatch)

    llm.before = LLMClientError("전송 오류")
    unavailable = await db_client.post(url)
    after_failure = await _calls(db_session, job_id)
    llm.before = None
    answered = await db_client.post(url)

    assert unavailable.status_code == 503, unavailable.text
    assert after_failure == []
    assert answered.status_code == 200, answered.text
    (record,) = await _calls(db_session, job_id)
    _assert_shape(record, with_usage=True)
    assert (record["callSite"], record["stage"], record["routeSource"], record["failure"]) == (
        "novelize_revise_recheck",
        "recheck",
        "env",
        None,
    )


# ── 응답·스키마 ─────────────────────────────────────────────────────────────
async def test_the_record_is_not_in_the_job_response_nor_in_the_api_schema(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """기록은 원가 분석용이다 — 작업 폴링 응답과 API 스키마에 싣지 않는다. 깨지는 시나리오: 응답 모델에 칸이 새어 사용자 화면으로
    모델 id·토큰이 나간다."""
    room, novel_id = await _novel_setup(db_client, db_session, monkeypatch)
    messages = await _room_messages(db_session, room.room_id)
    job = await _queue_job(db_session, novel_id, messages[0], room.turns[1][1])
    await db_session.execute(
        sa.update(NovelJob)
        .where(NovelJob.id == job.id)
        .values(llm_calls=[{"callSite": "novelize_chapter", "model": "fixture-model"}])
    )
    await db_session.commit()

    polled = await db_client.get(f"/novels/{novel_id}/jobs/{job.id}")

    assert polled.status_code == 200, polled.text
    assert "llmCalls" not in polled.text and "llm_calls" not in polled.text
    schema = json.dumps(app.openapi())
    assert "llmCalls" not in schema and "llm_calls" not in schema
