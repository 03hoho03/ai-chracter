"""소설화 작업 실행 — 상태 흐름(대기 → 실행 → 성공/실패), 결과 판정, 환불, heartbeat, 만료 정리, 폴링.

작업은 `create_charged_job` 으로 만들고(차감 포함) `run_job` 을 직접 기다려 돌린다. 라우트가 띄우는 백그라운드 태스크와
같은 함수이고, 직접 기다리면 끝난 시점이 정해져 테스트가 기다림 루프 없이 결과를 본다. 세션 팩토리는 `db_client`
처럼 테스트 커넥션 하나에 묶여 있어, 작업 본문과 heartbeat 가 동시에 쓰면 그 커넥션에서 부딪힌다 — 그래서 실행
테스트는 heartbeat 주기를 크게 늘려 두고, heartbeat 는 따로 시험한다. 테스트 안 `now()` 는 트랜잭션 시작 시각으로
고정이라 만료는 `heartbeat_at` 을 과거 값으로 넣어 만든다."""

import asyncio
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from api.core.config import settings
from api.db.models import ChatMessage, ChatRoom, Novel, NovelChapter, NovelChapterRevision, NovelJob
from api.db.models.clover import CloverLedger
from api.db.models.novel import NovelJobFailureCode
from api.llm.client import (
    LLMCallContext,
    LLMClient,
    LLMClientError,
    LLMEmptyResponseError,
    LLMPolicyViolationError,
    LLMRateLimitError,
    LLMTruncatedError,
    T,
)
from api.novelize import billing, runner
from api.novelize.deletion import delete_novels
from api.novelize.source import segment_hash
from factories import (
    Room,
    _grant_novelize,
    _login_as,
    _make_user_with_clover_lot,
    _open_room,
    _open_transaction_probe,
)

_BODY = "비가 내리는 저녁이었다. 서진은 가방을 내려놓고 창가에 섰다.\n\n" + "도윤이 잔을 밀어 주었다. " * 20


class _NovelLLM(LLMClient):
    """소설화 페이크. 장 생성은 `chunks` 를 흘린 뒤 `error` 가 있으면 그것을 낸다(본문 일부를 이미 흘린 뒤 실패하는
    실제 스트림과 같은 모양). 문단 수정은 `paragraphs` 를 돌려주거나 `error` 를 낸다. `during` 은 모델을 부르는 순간
    실행할 일(그 사이 다른 경로가 끼어드는 상황)이다."""

    def __init__(
        self,
        chunks: list[str] | None = None,
        *,
        error: Exception | None = None,
        paragraphs: list[str] | None = None,
        during: Callable[[], Awaitable[None]] | None = None,
    ) -> None:
        self.chunks = chunks if chunks is not None else [_BODY]
        self.error = error
        self.paragraphs = paragraphs
        self.during = during
        self.calls: list[tuple[str, str | None, LLMCallContext]] = []

    async def generate(
        self,
        prompt: str,
        system_instruction: str | None = None,
        stop_sequences: list[str] | None = None,
        *,
        usage: LLMCallContext,
    ) -> AsyncIterator[str]:
        self.calls.append((prompt, system_instruction, usage))
        if self.during is not None:
            await self.during()
        for chunk in self.chunks:
            yield chunk
        if self.error is not None:
            raise self.error

    async def generate_structured(
        self, prompt: str, response_schema: Any, images: Any = None, *, usage: LLMCallContext
    ) -> Any:
        raise AssertionError("소설화는 지시문 없는 구조화 호출을 쓰지 않는다")

    async def generate_structured_with_instruction(
        self, prompt: str, response_schema: type[T], *, system_instruction: str, usage: LLMCallContext
    ) -> T:
        self.calls.append((prompt, system_instruction, usage))
        if self.during is not None:
            await self.during()
        if self.error is not None:
            raise self.error
        return response_schema.model_validate({"paragraphs": self.paragraphs or []})


@pytest.fixture(autouse=True)
def _slow_heartbeat(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "novelize_heartbeat_interval_seconds", 3600)


def _factory(db_session: AsyncSession) -> async_sessionmaker[AsyncSession]:
    """작업 실행이 여는 세션. SAVEPOINT 로 붙여, 실행 경로의 롤백이 테스트 셋업까지 지우지 않게 한다."""
    return async_sessionmaker(bind=db_session.bind, expire_on_commit=False, join_transaction_mode="create_savepoint")


async def _novel_for(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    *,
    turns: int = 3,
    lane: str = "character",
    protagonist: str | None = "서진",
) -> tuple[Room, Novel]:
    owner = await _make_user_with_clover_lot(db_session, clover_balance=100)
    room = await _open_room(db_client, db_session, turns=turns, lane=lane, user=owner)
    chat_room = await db_session.get(ChatRoom, room.room_id)
    assert chat_room is not None
    novel = Novel(
        user_id=owner.id,
        chat_room_id=room.room_id,
        content_id=chat_room.content_id,
        content_type="story" if lane == "story" else "character",
        content_title="원작",
        character_name=None if lane == "story" else "캐릭터",
        protagonist_name=protagonist,
    )
    db_session.add(novel)
    await db_session.commit()
    return room, novel


async def _room_messages(db: AsyncSession, room_id: uuid.UUID) -> list[ChatMessage]:
    rows = await db.scalars(
        sa.select(ChatMessage).where(ChatMessage.chat_room_id == room_id).order_by(ChatMessage.created_at, ChatMessage.id)
    )
    return list(rows.all())


async def _chapter_job(
    db_session: AsyncSession, novel: Novel, start: ChatMessage, end: ChatMessage, *, chapter: NovelChapter | None = None
) -> NovelJob:
    job = NovelJob(
        novel_id=novel.id,
        user_id=novel.user_id,
        kind="chapter_regenerate" if chapter is not None else "chapter_generate",
        chapter_id=chapter.id if chapter is not None else None,
        start_message_id=start.id,
        start_message_created_at=start.created_at,
        end_message_id=end.id,
        end_message_created_at=end.created_at,
    )
    return await billing.create_charged_job(db_session, job=job, expected_cost=20, now=datetime.now(UTC))


async def _ledger(db: AsyncSession, user_id: uuid.UUID) -> list[tuple[str, int]]:
    rows = await db.execute(
        sa.select(CloverLedger.kind, CloverLedger.amount)
        .where(CloverLedger.user_id == user_id)
        .order_by(CloverLedger.amount, CloverLedger.kind)
    )
    return [(kind, amount) for kind, amount in rows.all()]


async def _job(db: AsyncSession, job_id: uuid.UUID) -> NovelJob:
    job = await db.scalar(
        sa.select(NovelJob).where(NovelJob.id == job_id).execution_options(populate_existing=True)
    )
    assert job is not None
    return job


async def _chapters(db: AsyncSession, novel_id: uuid.UUID) -> list[NovelChapter]:
    rows = await db.scalars(sa.select(NovelChapter).where(NovelChapter.novel_id == novel_id).order_by(NovelChapter.ordinal))
    return list(rows.all())


async def _revisions(db: AsyncSession, chapter_id: uuid.UUID) -> list[NovelChapterRevision]:
    rows = await db.scalars(
        sa.select(NovelChapterRevision)
        .where(NovelChapterRevision.chapter_id == chapter_id)
        .order_by(NovelChapterRevision.revision_no)
    )
    return list(rows.all())


async def _assert_failed_and_refunded_once(
    db: AsyncSession, job_id: uuid.UUID, user_id: uuid.UUID, code: NovelJobFailureCode, charged: int = 20
) -> None:
    job = await _job(db, job_id)
    assert (job.status, job.failure_code, job.refunded_at is not None) == ("failed", code, True)
    assert await _ledger(db, user_id) == [("novelize_spend", -charged), ("novelize_refund", charged)]


# ── 장 생성 성공 ────────────────────────────────────────────────────────────
async def test_chapter_job_saves_the_chapter_and_its_first_revision_after_the_status_flip(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    room, novel = await _novel_for(db_client, db_session)
    messages = await _room_messages(db_session, room.room_id)
    opening, a2 = messages[0], room.turns[2][1]
    job = await _chapter_job(db_session, novel, opening, a2)
    llm = _NovelLLM(chunks=["[턴 1] 비가 내리는 ", "저녁이었다.\n\n\n\n", "도윤이 잔을 밀어 주었다. " * 20])

    await runner.run_job(_factory(db_session), llm, job.id)

    stored = await _job(db_session, job.id)
    chapters = await _chapters(db_session, novel.id)
    assert len(chapters) == 1
    chapter = chapters[0]
    segment = messages[: messages.index(a2) + 1]
    assert (chapter.ordinal, chapter.start_message_id, chapter.end_message_id) == (1, opening.id, a2.id)
    assert chapter.assistant_message_count == 3
    assert chapter.source_hash == segment_hash(segment)
    revisions = await _revisions(db_session, chapter.id)
    assert [(r.revision_no, r.source) for r in revisions] == [(1, "generate")]
    assert revisions[0].body == "비가 내리는 저녁이었다.\n\n" + ("도윤이 잔을 밀어 주었다. " * 20).strip()
    assert (stored.status, stored.chapter_id, stored.result_revision_id) == ("succeeded", chapter.id, revisions[0].id)
    assert stored.finished_at is not None and stored.refunded_at is None
    assert await _ledger(db_session, novel.user_id) == [("novelize_spend", -20)]

    prompt, system_instruction, usage = llm.calls[0]
    assert (usage.call_site, usage.user_id, usage.room_id) == ("novelize_chapter", novel.user_id, room.room_id)
    assert system_instruction is not None and "3인칭" in system_instruction
    assert "[턴 1] 캐릭터: 인트로" in prompt
    assert "[턴 3] 사용자: [U02]" in prompt and "[턴 3] 캐릭터: [A02]" in prompt
    assert "[U03]" not in prompt
    assert "이름: 서진" in prompt
    assert "[앞 장의 끝]" not in prompt


async def test_next_chapter_carries_the_end_of_the_previous_chapter_and_gets_the_next_ordinal(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "novelize_previous_excerpt_chars", 10)
    room, novel = await _novel_for(db_client, db_session)
    messages = await _room_messages(db_session, room.room_id)
    first = await _chapter_job(db_session, novel, messages[0], room.turns[1][1])
    await runner.run_job(_factory(db_session), _NovelLLM(chunks=["앞 문단 " * 40 + "\n\n마지막 문단이다."]), first.id)

    second = await _chapter_job(db_session, novel, room.turns[2][0], room.turns[3][1])
    llm = _NovelLLM()
    await runner.run_job(_factory(db_session), llm, second.id)

    assert [c.ordinal for c in await _chapters(db_session, novel.id)] == [1, 2]
    prompt = llm.calls[0][0]
    assert "[앞 장의 끝]" in prompt and "마지막 문단이다." in prompt and "앞 문단" not in prompt
    assert "[턴 1] 사용자: [U02]" in prompt


async def test_story_novel_uses_the_story_setting_and_the_narrator_label(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    room, novel = await _novel_for(db_client, db_session, lane="story")
    messages = await _room_messages(db_session, room.room_id)
    job = await _chapter_job(db_session, novel, messages[0], room.turns[1][1])
    llm = _NovelLLM()

    await runner.run_job(_factory(db_session), llm, job.id)

    assert (await _job(db_session, job.id)).status == "succeeded"
    prompt = llm.calls[0][0]
    assert "세계관 설정" in prompt
    assert "[턴 1] 진행자: " in prompt


# ── 재생성 ──────────────────────────────────────────────────────────────────
async def _first_chapter(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> tuple[Room, Novel, NovelChapter, list[ChatMessage]]:
    room, novel = await _novel_for(db_client, db_session)
    messages = await _room_messages(db_session, room.room_id)
    job = await _chapter_job(db_session, novel, messages[0], room.turns[2][1])
    await runner.run_job(_factory(db_session), _NovelLLM(), job.id)
    (chapter,) = await _chapters(db_session, novel.id)
    return room, novel, chapter, messages


async def test_regenerate_adds_a_new_revision_to_the_same_chapter(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    room, novel, chapter, messages = await _first_chapter(db_client, db_session)
    job = await _chapter_job(db_session, novel, messages[0], room.turns[2][1], chapter=chapter)

    await runner.run_job(_factory(db_session), _NovelLLM(chunks=["다시 쓴 장. " * 30]), job.id)

    revisions = await _revisions(db_session, chapter.id)
    assert [(r.revision_no, r.source) for r in revisions] == [(1, "generate"), (2, "regenerate")]
    stored = await _job(db_session, job.id)
    assert (stored.status, stored.chapter_id, stored.result_revision_id) == ("succeeded", chapter.id, revisions[1].id)
    assert len(await _chapters(db_session, novel.id)) == 1


async def test_regenerate_after_the_source_changed_refunds_without_calling_the_model(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    room, novel, chapter, messages = await _first_chapter(db_client, db_session)
    await db_session.execute(
        sa.update(ChatMessage).where(ChatMessage.id == room.turns[1][0].id).values(content="고친 말")
    )
    job = await _chapter_job(db_session, novel, messages[0], room.turns[2][1], chapter=chapter)
    llm = _NovelLLM()

    await runner.run_job(_factory(db_session), llm, job.id)

    assert llm.calls == []
    job_row = await _job(db_session, job.id)
    assert (job_row.status, job_row.failure_code) == ("failed", "source_changed")
    assert [r.revision_no for r in await _revisions(db_session, chapter.id)] == [1]
    assert await _ledger(db_session, novel.user_id) == [
        ("novelize_spend", -20),
        ("novelize_spend", -20),
        ("novelize_refund", 20),
    ]


async def test_chapter_whose_end_message_disappeared_is_refunded_as_source_changed(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    room, novel = await _novel_for(db_client, db_session)
    messages = await _room_messages(db_session, room.room_id)
    job = await _chapter_job(db_session, novel, messages[0], room.turns[2][1])
    await db_session.execute(sa.delete(ChatMessage).where(ChatMessage.id == room.turns[2][1].id))

    await runner.run_job(_factory(db_session), _NovelLLM(), job.id)

    await _assert_failed_and_refunded_once(db_session, job.id, novel.user_id, "source_changed")
    assert await _chapters(db_session, novel.id) == []


# ── 실패 판정 → 환불 ────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    ("llm", "code"),
    [
        pytest.param(_NovelLLM(chunks=["잘린 본문 " * 50], error=LLMTruncatedError("cut")), "truncated", id="truncated"),
        pytest.param(_NovelLLM(chunks=[], error=LLMEmptyResponseError("empty")), "empty", id="empty"),
        pytest.param(_NovelLLM(chunks=["본문 일부"], error=LLMPolicyViolationError("blocked")), "blocked", id="blocked"),
        pytest.param(_NovelLLM(chunks=[], error=LLMRateLimitError("429")), "llm_error", id="rate-limit"),
        pytest.param(_NovelLLM(chunks=[], error=LLMClientError("down")), "llm_error", id="client-error"),
        pytest.param(_NovelLLM(chunks=["짧다."]), "empty", id="near-empty"),
        pytest.param(
            _NovelLLM(chunks=["죄송하지만 이 장면은 콘텐츠 정책상 작성해 드릴 수 없습니다. " * 10]),
            "refused",
            id="refusal",
        ),
    ],
)
async def test_failed_generation_is_refunded_once_and_saves_nothing(
    db_client: httpx.AsyncClient, db_session: AsyncSession, llm: _NovelLLM, code: NovelJobFailureCode
) -> None:
    room, novel = await _novel_for(db_client, db_session)
    messages = await _room_messages(db_session, room.room_id)
    job = await _chapter_job(db_session, novel, messages[0], room.turns[1][1])

    await runner.run_job(_factory(db_session), llm, job.id)

    await _assert_failed_and_refunded_once(db_session, job.id, novel.user_id, code)
    assert await _chapters(db_session, novel.id) == []
    assert (await _job(db_session, job.id)).result_text is None


async def test_job_over_the_overall_limit_is_refunded_as_timeout(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "novelize_job_timeout_seconds", 0.5)
    room, novel = await _novel_for(db_client, db_session)
    messages = await _room_messages(db_session, room.room_id)
    job = await _chapter_job(db_session, novel, messages[0], room.turns[1][1])

    await runner.run_job(_factory(db_session), _NovelLLM(during=lambda: asyncio.sleep(5)), job.id)

    await _assert_failed_and_refunded_once(db_session, job.id, novel.user_id, "timeout")


async def test_unexpected_error_is_refunded_reported_and_does_not_escape(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: list[str] = []
    monkeypatch.setattr(
        runner, "capture_dependency_failure", lambda exc=None, *, dependency: captured.append(dependency)
    )
    room, novel = await _novel_for(db_client, db_session)
    messages = await _room_messages(db_session, room.room_id)
    job = await _chapter_job(db_session, novel, messages[0], room.turns[1][1])

    await runner.run_job(_factory(db_session), _NovelLLM(error=RuntimeError("bug")), job.id)

    await _assert_failed_and_refunded_once(db_session, job.id, novel.user_id, "internal")
    assert captured == ["novelize"]


async def test_missing_protagonist_name_is_refunded_without_calling_the_model(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    room, novel = await _novel_for(db_client, db_session, protagonist=None)
    messages = await _room_messages(db_session, room.room_id)
    job = await _chapter_job(db_session, novel, messages[0], room.turns[1][1])
    llm = _NovelLLM()

    await runner.run_job(_factory(db_session), llm, job.id)

    assert llm.calls == []
    await _assert_failed_and_refunded_once(db_session, job.id, novel.user_id, "internal")


# ── 경합 ────────────────────────────────────────────────────────────────────
async def test_model_call_holds_no_db_session(db_client: httpx.AsyncClient, db_session: AsyncSession) -> None:
    room, novel = await _novel_for(db_client, db_session)
    messages = await _room_messages(db_session, room.room_id)
    job = await _chapter_job(db_session, novel, messages[0], room.turns[1][1])
    seen: list[int] = []

    with _open_transaction_probe() as open_sessions:

        async def note() -> None:
            seen.append(len(open_sessions - {id(db_session.sync_session)}))

        await runner.run_job(_factory(db_session), _NovelLLM(during=note), job.id)

    assert seen == [0]
    assert (await _job(db_session, job.id)).status == "succeeded"


async def test_result_arriving_after_cleanup_failed_the_job_is_discarded(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "novelize_heartbeat_expiry_seconds", 60)
    room, novel = await _novel_for(db_client, db_session)
    messages = await _room_messages(db_session, room.room_id)
    job = await _chapter_job(db_session, novel, messages[0], room.turns[1][1])
    factory = _factory(db_session)

    async def cleanup_wins() -> None:
        async with factory() as s:
            await s.execute(
                sa.update(NovelJob).where(NovelJob.id == job.id).values(heartbeat_at=sa.func.now() - timedelta(hours=1))
            )
            assert await runner.expire_stale_jobs(s, novel_id=novel.id) == 1
            await s.commit()

    await runner.run_job(factory, _NovelLLM(during=cleanup_wins), job.id)

    await _assert_failed_and_refunded_once(db_session, job.id, novel.user_id, "expired")
    assert await _chapters(db_session, novel.id) == []


async def test_novel_deleted_mid_job_leaves_nothing_and_raises_nothing(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    room, novel = await _novel_for(db_client, db_session)
    messages = await _room_messages(db_session, room.room_id)
    job = await _chapter_job(db_session, novel, messages[0], room.turns[1][1])
    factory = _factory(db_session)

    async def delete_novel() -> None:
        async with factory() as s:
            await billing.refund_active_jobs(s, novel_id=novel.id, failure_code="internal")
            await delete_novels(s, [novel.id])
            await s.commit()

    await runner.run_job(factory, _NovelLLM(during=delete_novel), job.id)

    assert await db_session.scalar(sa.select(Novel.id).where(Novel.id == novel.id)) is None
    assert await db_session.scalar(sa.select(sa.func.count()).select_from(NovelChapter)) == 0
    assert await _ledger(db_session, novel.user_id) == [("novelize_spend", -20), ("novelize_refund", 20)]


async def test_job_already_finished_before_it_starts_is_left_alone(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    room, novel = await _novel_for(db_client, db_session)
    messages = await _room_messages(db_session, room.room_id)
    job = await _chapter_job(db_session, novel, messages[0], room.turns[1][1])
    await billing.refund_job(db_session, job_id=job.id, failure_code="expired")
    await db_session.commit()
    llm = _NovelLLM()

    await runner.run_job(_factory(db_session), llm, job.id)

    assert llm.calls == []
    await _assert_failed_and_refunded_once(db_session, job.id, novel.user_id, "expired")


# ── AI 문단 수정 ────────────────────────────────────────────────────────────
async def _ai_edit_job(
    db_session: AsyncSession, novel: Novel, chapter: NovelChapter, *, start: int, end: int
) -> NovelJob:
    base = (await _revisions(db_session, chapter.id))[-1]
    job = NovelJob(
        novel_id=novel.id,
        user_id=novel.user_id,
        kind="ai_edit",
        chapter_id=chapter.id,
        base_revision_id=base.id,
        paragraph_start=start,
        paragraph_end=end,
        instruction="더 쓸쓸하게",
    )
    return await billing.create_charged_job(db_session, job=job, expected_cost=5, now=datetime.now(UTC))


async def _chapter_with_body(db_client: httpx.AsyncClient, db_session: AsyncSession, body: str) -> tuple[Novel, NovelChapter]:
    room, novel = await _novel_for(db_client, db_session)
    messages = await _room_messages(db_session, room.room_id)
    job = await _chapter_job(db_session, novel, messages[0], room.turns[1][1])
    await runner.run_job(_factory(db_session), _NovelLLM(chunks=[body]), job.id)
    (chapter,) = await _chapters(db_session, novel.id)
    return novel, chapter


async def test_ai_edit_keeps_a_preview_of_the_whole_body_and_makes_no_revision(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    paragraphs = ["첫째 문단이다." * 30, "둘째 문단이다.", "셋째 문단이다.", "넷째 문단이다."]
    novel, chapter = await _chapter_with_body(db_client, db_session, "\n\n".join(paragraphs))
    job = await _ai_edit_job(db_session, novel, chapter, start=1, end=2)
    llm = _NovelLLM(paragraphs=["[2] 고친 둘째.", "고친 셋째.\n\n새로 나눈 문단."])

    await runner.run_job(_factory(db_session), llm, job.id)

    stored = await _job(db_session, job.id)
    assert stored.status == "succeeded"
    assert stored.result_text == "\n\n".join(
        [paragraphs[0], "고친 둘째.", "고친 셋째.", "새로 나눈 문단.", paragraphs[3]]
    )
    assert stored.result_revision_id is None
    assert [r.revision_no for r in await _revisions(db_session, chapter.id)] == [1]
    prompt, system_instruction, usage = llm.calls[0]
    assert usage.call_site == "novelize_revise"
    assert system_instruction is not None and "[고치는 규칙]" in system_instruction
    assert "[2] 둘째 문단이다." in prompt and "2번 문단부터 3번 문단까지" in prompt and "더 쓸쓸하게" in prompt


@pytest.mark.parametrize(
    ("paragraphs", "code"),
    [
        pytest.param([], "empty", id="no-paragraphs"),
        pytest.param(["  ", "\n"], "empty", id="blank-paragraphs"),
        pytest.param(["죄송하지만 그 요청은 도와드릴 수 없습니다."], "refused", id="refusal"),
    ],
)
async def test_unusable_ai_edit_is_refunded(
    db_client: httpx.AsyncClient, db_session: AsyncSession, paragraphs: list[str], code: NovelJobFailureCode
) -> None:
    novel, chapter = await _chapter_with_body(db_client, db_session, "\n\n".join(["문단이다. " * 40, "둘째."]))
    job = await _ai_edit_job(db_session, novel, chapter, start=0, end=0)

    await runner.run_job(_factory(db_session), _NovelLLM(paragraphs=paragraphs), job.id)

    stored = await _job(db_session, job.id)
    assert (stored.status, stored.failure_code, stored.result_text) == ("failed", code, None)
    assert await _ledger(db_session, novel.user_id) == [
        ("novelize_spend", -20),
        ("novelize_spend", -5),
        ("novelize_refund", 5),
    ]


async def test_ai_edit_after_the_room_is_gone_reads_the_current_published_setting(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    novel, chapter = await _chapter_with_body(db_client, db_session, "\n\n".join(["문단이다. " * 40, "둘째."]))
    await db_session.execute(sa.update(Novel).where(Novel.id == novel.id).values(chat_room_id=None))
    job = await _ai_edit_job(db_session, novel, chapter, start=1, end=1)
    llm = _NovelLLM(paragraphs=["고친 둘째."])

    await runner.run_job(_factory(db_session), llm, job.id)

    assert (await _job(db_session, job.id)).status == "succeeded"
    prompt, _, usage = llm.calls[0]
    assert usage.room_id is None
    assert "이름: 캐릭터\n프롬프트" in prompt


# ── heartbeat · 만료 정리 ───────────────────────────────────────────────────
async def test_heartbeat_moves_only_a_running_job(db_client: httpx.AsyncClient, db_session: AsyncSession) -> None:
    room, novel = await _novel_for(db_client, db_session)
    messages = await _room_messages(db_session, room.room_id)
    job = await _chapter_job(db_session, novel, messages[0], room.turns[1][1])
    old = datetime.now(UTC) - timedelta(hours=1)
    await db_session.execute(
        sa.update(NovelJob).where(NovelJob.id == job.id).values(status="running", heartbeat_at=old)
    )
    await db_session.commit()

    await runner.beat(_factory(db_session), job.id)
    beat = (await _job(db_session, job.id)).heartbeat_at
    assert beat is not None and beat > old

    for status in ("queued", "failed"):
        await db_session.execute(
            sa.update(NovelJob).where(NovelJob.id == job.id).values(status=status, heartbeat_at=old)
        )
        await runner.beat(_factory(db_session), job.id)
        assert (await _job(db_session, job.id)).heartbeat_at == old


async def test_heartbeat_keeps_beating_after_a_failed_beat(monkeypatch: pytest.MonkeyPatch) -> None:
    """한 번 실패해도 멈추지 않는다 — 멈추면 살아 있는 작업이 만료 정리에 환불되고 결과가 버려진다."""
    monkeypatch.setattr(settings, "novelize_heartbeat_interval_seconds", 0.001)
    beats: list[int] = []
    third = asyncio.Event()

    async def flaky_beat(_factory: Any, _job_id: uuid.UUID) -> None:
        beats.append(len(beats))
        if len(beats) == 1:
            raise RuntimeError("db down")
        if len(beats) == 3:
            third.set()

    monkeypatch.setattr(runner, "beat", flaky_beat)
    task = asyncio.ensure_future(runner.keep_job_alive(async_sessionmaker(), uuid.uuid4()))
    await asyncio.wait_for(third.wait(), 5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert len(beats) >= 3


async def test_expiry_refunds_only_stale_active_jobs_of_that_novel(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "novelize_heartbeat_expiry_seconds", 60)
    room, novel = await _novel_for(db_client, db_session)
    messages = await _room_messages(db_session, room.room_id)
    stale = await _chapter_job(db_session, novel, messages[0], room.turns[1][1])
    _, other = await _novel_for(db_client, db_session)
    other_messages = await _room_messages(db_session, other.chat_room_id or uuid.uuid4())
    other_stale = await _chapter_job(db_session, other, other_messages[0], other_messages[2])
    for job_id in (stale.id, other_stale.id):
        await db_session.execute(
            sa.update(NovelJob)
            .where(NovelJob.id == job_id)
            .values(heartbeat_at=sa.func.now() - timedelta(seconds=61))
        )

    assert await runner.expire_stale_jobs(db_session, novel_id=novel.id) == 1
    await db_session.commit()

    await _assert_failed_and_refunded_once(db_session, stale.id, novel.user_id, "expired")
    assert (await _job(db_session, other_stale.id)).status == "queued"

    # 만료 경계 안쪽(59초 전)은 살아 있는 작업이다.
    fresh = await _chapter_job(db_session, novel, room.turns[2][0], room.turns[2][1])
    await db_session.execute(
        sa.update(NovelJob).where(NovelJob.id == fresh.id).values(heartbeat_at=sa.func.now() - timedelta(seconds=59))
    )
    assert await runner.expire_stale_jobs(db_session, novel_id=novel.id) == 0
    assert (await _job(db_session, fresh.id)).status == "queued"


# ── 띄우기 ──────────────────────────────────────────────────────────────────
async def test_enqueued_job_runs_in_the_background(db_client: httpx.AsyncClient, db_session: AsyncSession) -> None:
    room, novel = await _novel_for(db_client, db_session)
    messages = await _room_messages(db_session, room.room_id)
    job = await _chapter_job(db_session, novel, messages[0], room.turns[1][1])

    await runner.enqueue_job(_factory(db_session), _NovelLLM(), job.id)
    # 테스트 커넥션은 하나라 백그라운드 작업이 끝나기 전에 같은 커넥션으로 읽으면 부딪힌다 — 태스크를 기다린다.
    await asyncio.gather(*runner._background_tasks)
    assert (await _job(db_session, job.id)).status == "succeeded"


async def test_job_that_could_not_be_started_is_refunded_at_once(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    room, novel = await _novel_for(db_client, db_session)
    messages = await _room_messages(db_session, room.room_id)
    job = await _chapter_job(db_session, novel, messages[0], room.turns[1][1])

    def broken_spawn(coro: Any) -> None:
        coro.close()
        raise RuntimeError("no loop")

    monkeypatch.setattr(runner, "_spawn", broken_spawn)
    await runner.enqueue_job(_factory(db_session), _NovelLLM(), job.id)

    await _assert_failed_and_refunded_once(db_session, job.id, novel.user_id, "internal")


# ── 폴링 ────────────────────────────────────────────────────────────────────
async def _allow(db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, user_id: uuid.UUID) -> None:
    monkeypatch.setattr(settings, "novelize_enabled", True)
    monkeypatch.setattr(settings, "novelize_grant_allowlist", [user_id])
    await _grant_novelize(db_session, user_id)
    await db_session.commit()


async def test_poll_reports_a_finished_chapter_job(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    room, novel = await _novel_for(db_client, db_session)
    await _allow(db_session, monkeypatch, novel.user_id)
    messages = await _room_messages(db_session, room.room_id)
    job = await _chapter_job(db_session, novel, messages[0], room.turns[1][1])
    await runner.run_job(_factory(db_session), _NovelLLM(), job.id)
    stored = await _job(db_session, job.id)

    resp = await db_client.get(f"/novels/{novel.id}/jobs/{job.id}")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body == {
        "id": str(job.id),
        "kind": "chapter_generate",
        "status": "succeeded",
        "chargedAmount": 20,
        "refunded": False,
        "failureReason": None,
        "chapterId": str(stored.chapter_id),
        "revisionId": str(stored.result_revision_id),
        "aiEdit": None,
        "createdAt": body["createdAt"],
    }


async def test_poll_reports_an_ai_edit_preview(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    novel, chapter = await _chapter_with_body(db_client, db_session, "\n\n".join(["문단이다. " * 40, "둘째."]))
    await _allow(db_session, monkeypatch, novel.user_id)
    job = await _ai_edit_job(db_session, novel, chapter, start=1, end=1)
    await runner.run_job(_factory(db_session), _NovelLLM(paragraphs=["고친 둘째."]), job.id)
    await _job(db_session, job.id)  # 라우트가 이 테스트 세션을 쓰므로 붙잡힌 옛 상태를 새로 읽어 둔다

    resp = await db_client.get(f"/novels/{novel.id}/jobs/{job.id}")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    base = (await _revisions(db_session, chapter.id))[0]
    assert (body["kind"], body["status"], body["chapterId"], body["revisionId"]) == (
        "ai_edit",
        "succeeded",
        str(chapter.id),
        None,
    )
    assert body["aiEdit"] == {
        "baseRevisionId": str(base.id),
        "paragraphStart": 1,
        "paragraphEnd": 1,
        "instruction": "더 쓸쓸하게",
        "resultText": ("문단이다. " * 40).strip() + "\n\n고친 둘째.",
    }


async def test_poll_expires_a_dead_job_before_answering(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    room, novel = await _novel_for(db_client, db_session)
    await _allow(db_session, monkeypatch, novel.user_id)
    messages = await _room_messages(db_session, room.room_id)
    job = await _chapter_job(db_session, novel, messages[0], room.turns[1][1])
    await db_session.execute(
        sa.update(NovelJob).where(NovelJob.id == job.id).values(heartbeat_at=sa.func.now() - timedelta(hours=1))
    )
    await db_session.commit()

    resp = await db_client.get(f"/novels/{novel.id}/jobs/{job.id}")

    assert resp.status_code == 200, resp.text
    assert (resp.json()["status"], resp.json()["refunded"], resp.json()["failureReason"]) == ("failed", True, "expired")
    await _assert_failed_and_refunded_once(db_session, job.id, novel.user_id, "expired")


async def test_poll_hides_missing_and_foreign_jobs(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    room, novel = await _novel_for(db_client, db_session)
    messages = await _room_messages(db_session, room.room_id)
    job = await _chapter_job(db_session, novel, messages[0], room.turns[1][1])
    other_room, other = await _novel_for(db_client, db_session)
    await _allow(db_session, monkeypatch, other.user_id)
    other_messages = await _room_messages(db_session, other_room.room_id)
    other_job = await _chapter_job(db_session, other, other_messages[0], other_room.turns[1][1])
    await _login_as(db_client, other.user_id)

    foreign = await db_client.get(f"/novels/{novel.id}/jobs/{job.id}")
    crossed = await db_client.get(f"/novels/{other.id}/jobs/{job.id}")
    missing = await db_client.get(f"/novels/{other.id}/jobs/{uuid.uuid4()}")
    own = await db_client.get(f"/novels/{other.id}/jobs/{other_job.id}")

    assert [r.status_code for r in (foreign, crossed, missing, own)] == [404, 404, 404, 200]
    assert foreign.json()["detail"] == {"code": "NOVEL_JOB_NOT_FOUND"}


async def test_poll_is_behind_the_novelize_gate(db_client: httpx.AsyncClient, db_session: AsyncSession) -> None:
    room, novel = await _novel_for(db_client, db_session)
    messages = await _room_messages(db_session, room.room_id)
    job = await _chapter_job(db_session, novel, messages[0], room.turns[1][1])

    resp = await db_client.get(f"/novels/{novel.id}/jobs/{job.id}")

    assert resp.status_code == 403
    assert resp.json()["detail"] == {"code": "NOVELIZE_NOT_ALLOWED"}
