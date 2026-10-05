"""소설화 작업 실행 — 요청이 만든 작업 행(대기)을 백그라운드에서 돌려 성공으로 끝내거나 실패·환불한다.

**상태 흐름**: 요청이 `queued` + `heartbeat_at` 으로 행을 넣고 차감·커밋한 뒤 이 모듈로 띄운다 → `queued → running`
조건부 전이(받지 못하면 이미 정리된 작업이라 그냥 끝낸다) → 원문을 다시 읽고 입력을 만든다 → 모델 호출 → 결과 판정 →
성공 전이 + 저장, 또는 단일 환불 함수로 실패·환불.

**세션**: 요청 세션은 응답과 함께 닫히므로 쓰지 않고, 라우트가 넘긴 세션 팩토리로 단계마다 짧은 세션을 연다. 모델을
부르는 동안에는 세션을 쥐지 않는다 — 장 생성은 수 분까지 걸릴 수 있고, 그동안 커넥션을 붙잡으면 풀이 마른다.

**결과 저장 규칙**: 스트림 청크는 메모리에만 모은다(작업 행·heartbeat 에 본문을 싣지 않는다). 저장은 스트림이 예외
없이 끝까지 돈 뒤에만 한다 — 루프 안이나 `finally` 에서 저장하면 잘린 장이 저장된다. 중간에 끊지도 않는다(끊으면
잘림·빈 본문 판정과 사용량 기록이 일어나지 않는다). 성공 저장은 **작업 상태 전이를 먼저** 하고 장·개정을 나중에 넣는다
— 전이가 행을 받지 못하면(만료 정리가 먼저 실패·환불했거나 소설 삭제가 작업 행을 지웠으면) 결과를 버린다.

**작업 전체 상한**은 `asyncio.timeout` 이다. 상한에 걸리면 진행 중인 모델 호출이 취소되고, 취소된 호출의 토큰 사용량은
기록되지 않는다(사용량 기록은 정상 종료한 호출에만 있다). 서버 종료로 태스크가 취소되면(`CancelledError`) 잡지 않는다 —
heartbeat 가 멈춘 그 작업은 만료 정리가 환불한다."""

import asyncio
import logging
import re
import uuid
from collections.abc import Coroutine, Sequence
from datetime import timedelta
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from api.core.config import settings
from api.core.sentry import capture_dependency_failure
from api.db.models.novel import Novel, NovelChapter, NovelChapterRevision, NovelJob, NovelJobFailureCode
from api.llm.client import (
    LLMCallContext,
    LLMClient,
    LLMClientError,
    LLMEmptyResponseError,
    LLMPolicyViolationError,
    LLMTruncatedError,
)
from api.novelize.billing import ACTIVE_JOB_STATUSES, refund_job, transition_job
from api.novelize.inputs import (
    ChapterInput,
    SourceChangedError,
    build_chapter_input,
    build_revise_input,
    current_revision,
    next_ordinal,
)
from api.novelize.prompts import NovelizeReviseResult
from api.novelize.text import clean_chapter_body, looks_like_refusal, split_paragraphs

logger = logging.getLogger(__name__)

# 띄운 태스크의 강한 참조. 이벤트 루프는 태스크를 약하게만 잡아 참조가 없으면 도중에 수거될 수 있다.
_background_tasks: set[asyncio.Task[None]] = set()

SessionFactory = async_sessionmaker[AsyncSession]


class _JobFailedError(Exception):
    """예상한 실패 — 사유 코드로 환불한다(오류 보고는 하지 않는다)."""

    def __init__(self, code: NovelJobFailureCode) -> None:
        super().__init__(code)
        self.code = code


def _spawn(coro: Coroutine[Any, Any, None]) -> None:
    task = asyncio.create_task(coro)
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


async def enqueue_job(session_factory: SessionFactory, llm_client: LLMClient, job_id: uuid.UUID) -> None:
    """차감·커밋까지 끝난 작업을 백그라운드로 띄운다. 띄우지 못하면 그 자리에서 실패·환불한다 — 차감만 남고 아무도
    돌리지 않는 작업이 만료 정리를 기다리지 않게. 라우트는 이 함수를 부르고 202 를 돌려주면 된다."""
    try:
        _spawn(run_job(session_factory, llm_client, job_id))
    except Exception as exc:
        logger.warning("소설화 작업 %s 를 띄우지 못해 환불한다: %s", job_id, type(exc).__name__)
        capture_dependency_failure(exc, dependency="novelize")
        await _refund(session_factory, job_id, "internal")


async def run_job(session_factory: SessionFactory, llm_client: LLMClient, job_id: uuid.UUID) -> None:
    """작업 하나를 끝까지 돌린다. 예외를 밖으로 내지 않는다(취소만 예외) — 실패는 전부 환불로 끝낸다."""
    code: NovelJobFailureCode
    try:
        async with asyncio.timeout(settings.novelize_job_timeout_seconds):
            await _execute(session_factory, llm_client, job_id)
        return
    except _JobFailedError as failed:
        code = failed.code
    except TimeoutError:
        code = "timeout"
    except Exception as exc:
        logger.warning("소설화 작업 %s 가 예상하지 못한 오류로 실패했다: %s", job_id, type(exc).__name__)
        capture_dependency_failure(exc, dependency="novelize")
        code = "internal"
    await _refund(session_factory, job_id, code)


async def _refund(session_factory: SessionFactory, job_id: uuid.UUID, code: NovelJobFailureCode) -> None:
    """실패 확정 + 환불. 여기서 실패하면(DB 장애) 삼키고 남긴다 — 작업은 진행 중으로 남고 heartbeat 가 멈췄으므로
    만료 정리가 같은 환불 함수로 다시 환불한다."""
    try:
        async with session_factory() as db:
            await refund_job(db, job_id=job_id, failure_code=code)
            await db.commit()
    except Exception as exc:
        logger.warning("소설화 작업 %s 환불에 실패했다(만료 정리가 다시 한다): %s", job_id, type(exc).__name__)
        capture_dependency_failure(exc, dependency="novelize")


async def _execute(session_factory: SessionFactory, llm_client: LLMClient, job_id: uuid.UUID) -> None:
    async with session_factory() as db:
        started = await transition_job(
            db,
            job_id=job_id,
            expected=("queued",),
            values={"status": "running", "started_at": func.now(), "heartbeat_at": func.now()},
        )
        await db.commit()
    if started is None:
        return

    heartbeat = asyncio.create_task(keep_job_alive(session_factory, job_id))
    try:
        async with session_factory() as db:
            job = await db.get(NovelJob, job_id)
            novel = await db.get(Novel, job.novel_id) if job is not None else None
            if job is None or novel is None:
                return
            try:
                if job.kind == "ai_edit":
                    revise = await build_revise_input(db, job, novel)
                else:
                    chapter_input = await build_chapter_input(db, job, novel)
            except SourceChangedError as exc:
                raise _JobFailedError("source_changed") from exc
            usage = LLMCallContext(
                call_site="novelize_revise" if job.kind == "ai_edit" else "novelize_chapter",
                user_id=job.user_id,
                room_id=novel.chat_room_id,
            )
            kind = job.kind
        # 여기서부터 모델 호출 — 세션을 닫은 뒤다.
        if kind == "ai_edit":
            result_text = await _revise(llm_client, revise.prompt.prompt, revise.prompt.system_instruction, usage)
            body = _assemble_revision(revise.paragraphs, revise.first_index, revise.last_index, result_text)
            await _save_ai_edit(session_factory, job_id, body)
        else:
            body = await _generate_chapter(llm_client, chapter_input, usage)
            await _save_chapter(session_factory, job_id, chapter_input, body)
    finally:
        heartbeat.cancel()


async def _generate_chapter(llm_client: LLMClient, chapter_input: ChapterInput, usage: LLMCallContext) -> str:
    chunks: list[str] = []
    try:
        async for chunk in llm_client.generate(
            chapter_input.prompt.prompt, chapter_input.prompt.system_instruction, usage=usage
        ):
            chunks.append(chunk)
    except LLMTruncatedError as exc:
        raise _JobFailedError("truncated") from exc
    except LLMEmptyResponseError as exc:
        raise _JobFailedError("empty") from exc
    except LLMPolicyViolationError as exc:
        raise _JobFailedError("blocked") from exc
    except LLMClientError as exc:
        logger.warning("소설화 장 생성 호출이 실패했다: %s", type(exc).__name__)
        raise _JobFailedError("llm_error") from exc
    body = clean_chapter_body("".join(chunks))
    _judge(split_paragraphs(body))
    if len(body) < settings.novelize_min_chapter_chars:
        raise _JobFailedError("empty")
    return body


def _judge(paragraphs: list[str]) -> None:
    """본문형 거절 판정 — 모델이 장·문단 대신 거절이나 안내문을 썼으면 실패(환불)다. 판정 규칙은 `looks_like_refusal`
    한 곳에 있다. 별도 판정 호출을 쓰지 않는 이유는 그 호출이 장마다 원가·지연을 더하고 그 자체가 실패할 수 있어서다."""
    if looks_like_refusal(paragraphs):
        raise _JobFailedError("refused")


_LEADING_NUMBER = re.compile(r"^\[\d+\]\s*")


async def _revise(llm_client: LLMClient, prompt: str, system_instruction: str, usage: LLMCallContext) -> list[str]:
    try:
        result = await llm_client.generate_structured_with_instruction(
            prompt, NovelizeReviseResult, system_instruction=system_instruction, usage=usage
        )
    except LLMTruncatedError as exc:
        raise _JobFailedError("truncated") from exc
    except LLMEmptyResponseError as exc:
        raise _JobFailedError("empty") from exc
    except LLMPolicyViolationError as exc:
        raise _JobFailedError("blocked") from exc
    except LLMClientError as exc:
        logger.warning("소설화 문단 수정 호출이 실패했다: %s", type(exc).__name__)
        raise _JobFailedError("llm_error") from exc
    # 항목 안의 빈 줄은 문단을 나눈 것으로 보고, 앞에 붙어 온 `[n]` 번호는 걷는다.
    paragraphs = [
        part for item in result.paragraphs for part in split_paragraphs(_LEADING_NUMBER.sub("", item.strip()))
    ]
    if not paragraphs:
        raise _JobFailedError("empty")
    _judge(paragraphs)
    return paragraphs


def _assemble_revision(paragraphs: list[str], first: int, last: int, replacement: list[str]) -> str:
    """범위 밖 문단은 원본 그대로 붙인다 — 모델이 범위 밖을 고쳐 보냈어도 결과에 들어가지 않는다."""
    return "\n\n".join([*paragraphs[:first], *replacement, *paragraphs[last + 1 :]])


async def _save_ai_edit(session_factory: SessionFactory, job_id: uuid.UUID, body: str) -> None:
    """문단 수정 결과는 개정이 아니라 미리보기 후보다. 사용자가 적용할 때 새 개정이 된다. 전이와 결과 본문을 한
    문장으로 써서 전이가 행을 받지 못하면 결과도 남지 않는다."""
    async with session_factory() as db:
        await transition_job(
            db,
            job_id=job_id,
            expected=("running",),
            values={"status": "succeeded", "result_text": body, "finished_at": func.now()},
        )
        await db.commit()


async def _save_chapter(session_factory: SessionFactory, job_id: uuid.UUID, chapter_input: ChapterInput, body: str) -> None:
    async with session_factory() as db:
        if (
            await transition_job(
                db, job_id=job_id, expected=("running",), values={"status": "succeeded", "finished_at": func.now()}
            )
            is None
        ):
            await db.rollback()
            return
        job = await db.get(NovelJob, job_id)
        assert job is not None  # 방금 전이가 행을 받았고 같은 트랜잭션이 그 행을 잠그고 있다
        if job.kind == "chapter_regenerate":
            assert job.chapter_id is not None
            # 직접 수정·되돌리기도 장 행을 먼저 잠그고 다음 번호를 쓴다 — 같은 번호를 동시에 쓰지 않게 줄을 선다.
            await db.execute(
                select(NovelChapter.id).where(NovelChapter.id == job.chapter_id).with_for_update(key_share=True)
            )
            latest = await current_revision(db, job.chapter_id)
            chapter_id = job.chapter_id
            revision_no = (latest.revision_no if latest else 0) + 1
            source = "regenerate"
        else:
            assert (
                job.start_message_id is not None
                and job.start_message_created_at is not None
                and job.end_message_id is not None
                and job.end_message_created_at is not None
            )
            chapter = NovelChapter(
                novel_id=job.novel_id,
                ordinal=await next_ordinal(db, job.novel_id),
                start_message_id=job.start_message_id,
                start_message_created_at=job.start_message_created_at,
                end_message_id=job.end_message_id,
                end_message_created_at=job.end_message_created_at,
                assistant_message_count=chapter_input.assistant_count,
                source_hash=chapter_input.source_hash,
            )
            db.add(chapter)
            await db.flush()
            chapter_id, revision_no, source = chapter.id, 1, "generate"
        revision = NovelChapterRevision(chapter_id=chapter_id, revision_no=revision_no, body=body, source=source)
        db.add(revision)
        await db.flush()
        # 결과 개정을 가리키는 칸은 개정을 넣은 뒤에야 채울 수 있다(FK 를 바로 검사한다).
        await db.execute(
            update(NovelJob).where(NovelJob.id == job_id).values(chapter_id=chapter_id, result_revision_id=revision.id)
        )
        await db.execute(update(Novel).where(Novel.id == job.novel_id).values(updated_at=func.now()))
        await db.commit()


async def keep_job_alive(session_factory: SessionFactory, job_id: uuid.UUID) -> None:
    """작업이 도는 동안 `heartbeat_at` 을 주기적으로 민다. 취소될 때까지 돈다(작업 본문의 `finally` 가 취소한다).
    한 번 실패해도 멈추지 않는다: 만료 전에 계속 실패하면 작업이 환불되고 결과는 버려지지만, 그것 때문에 진행 중인
    생성을 멈추지는 않는다."""
    while True:
        await asyncio.sleep(settings.novelize_heartbeat_interval_seconds)
        try:
            await beat(session_factory, job_id)
        except Exception as exc:
            logger.warning("소설화 작업 %s heartbeat 갱신에 실패했다: %s", job_id, type(exc).__name__)


async def beat(session_factory: SessionFactory, job_id: uuid.UUID) -> None:
    """heartbeat 한 번 — DB 시각으로 민다(만료 비교도 DB 시계다). 실행 중인 작업만 민다: 이미 끝난 작업의 시각을
    바꾸지 않고, 아직 대기인 작업은 요청이 넣은 시각 그대로 만료를 센다."""
    async with session_factory() as db:
        await db.execute(
            update(NovelJob).where(NovelJob.id == job_id, NovelJob.status == "running").values(heartbeat_at=func.now())
        )
        await db.commit()


async def _stale_job_ids(db: AsyncSession, *, novel_id: uuid.UUID | None) -> Sequence[uuid.UUID]:
    """heartbeat 가 만료된 진행 중 작업. `novel_id` 가 None 이면 모든 소설에서 찾는다. 만료는 DB 시계로 비교한다(작업
    행의 시각도 DB 가 찍었다)."""
    cutoff = func.now() - timedelta(seconds=settings.novelize_heartbeat_expiry_seconds)
    query = select(NovelJob.id).where(NovelJob.status.in_(ACTIVE_JOB_STATUSES), NovelJob.heartbeat_at < cutoff)
    if novel_id is not None:
        query = query.where(NovelJob.novel_id == novel_id)
    return (await db.scalars(query.order_by(NovelJob.id))).all()


async def expire_stale_jobs(db: AsyncSession, *, novel_id: uuid.UUID) -> int:
    """소설의 진행 중 작업 중 heartbeat 가 만료된 것을 실패·환불하고 그 수를 돌려준다. 커밋은 호출자가 한다.

    폴링·소설 조회·새 작업 차감 직전에 부르는 지연 정리다. 기동 직후 곧바로 일괄 실패 처리를 하지 않는 것은 워커가
    여럿이라 다른 워커의 살아 있는 작업을 죽이기 때문이다(기동 뒤 정리는 만료를 기다렸다 돈다 —
    `expire_stale_jobs_after_startup`). 환불은 단일 환불 함수라 실행 경로의 실패 처리나 다른 요청의 정리와 겹쳐도 한
    번만 나간다."""
    expired = 0
    for job_id in await _stale_job_ids(db, novel_id=novel_id):
        if await refund_job(db, job_id=job_id, failure_code="expired") is not None:
            expired += 1
    return expired


async def expire_all_stale_jobs(session_factory: SessionFactory) -> int:
    """모든 소설의 만료된 작업을 실패·환불하고 그 수를 돌려준다. 작업마다 커밋한다 — 환불은 사용자 행을 잠그므로
    여러 사용자의 잠금을 한 트랜잭션에 쌓으면, 같은 정리를 도는 다른 워커나 그 사용자의 요청과 서로를 기다릴 수 있다.

    한 작업이 실패하면(그 사용자 행의 잠금 대기 초과 등) 그 작업만 되돌리고 남긴 뒤 다음 작업으로 넘어간다. 이 정리는
    기동마다 한 번뿐이라, 거기서 멈추면 뒤 작업들은 게이트가 닫힌 동안 다음 기동까지 묶인다. 되돌린 작업은 진행 중으로
    남아 다음 기동이나 지연 정리가 다시 본다."""
    expired = 0
    async with session_factory() as db:
        for job_id in await _stale_job_ids(db, novel_id=None):
            try:
                refunded = await refund_job(db, job_id=job_id, failure_code="expired") is not None
                await db.commit()
            except Exception as exc:
                await db.rollback()
                logger.warning(
                    "기동 뒤 정리에서 소설화 작업 %s 환불에 실패했다(다음 작업은 계속한다): %s",
                    job_id,
                    type(exc).__name__,
                )
                capture_dependency_failure(exc, dependency="novelize")
                continue
            if refunded:
                expired += 1
    return expired


# 기동 뒤 정리를 heartbeat 만료 시간보다 이만큼 더 늦게 돌린다. 직전 프로세스가 죽기 직전에 민 heartbeat 까지 확실히
# 만료된 뒤에 돌아야 그 작업들을 이번 한 번에 정리한다.
_STARTUP_EXPIRY_MARGIN_SECONDS = 10
# 테스트가 기다림을 건너뛰도록 바꿔 끼우는 자리.
_sleep = asyncio.sleep


async def expire_stale_jobs_after_startup(session_factory: SessionFactory) -> None:
    """프로세스 기동 뒤 한 번, heartbeat 만료 시간(+여유)을 기다렸다가 모든 소설의 죽은 작업을 정리한다.

    지연 정리는 사용자가 소설을 열거나 폴링할 때만 돌고 그 라우트는 모두 소설화 게이트 뒤에 있다. 킬 스위치를 끄거나
    명단에서 빼려면 재기동해야 하고, 재기동은 돌던 작업을 죽인다 — 그때 게이트가 닫혀 있으면 사용자가 돌아올 수
    없어 차감액이 묶인다. 그래서 이 정리는 게이트·킬 스위치를 보지 않는다. 워커마다 돌아도 상태 전이가 조건부라 한
    작업은 한 번만 환불된다. 실패는 삼키고 남긴다(그 작업은 다음 기동이나 지연 정리가 다시 본다)."""
    await _sleep(settings.novelize_heartbeat_expiry_seconds + _STARTUP_EXPIRY_MARGIN_SECONDS)
    try:
        expired = await expire_all_stale_jobs(session_factory)
    except Exception as exc:
        logger.warning("기동 뒤 소설화 만료 정리에 실패했다: %s", type(exc).__name__)
        capture_dependency_failure(exc, dependency="novelize")
        return
    if expired:
        logger.warning("기동 뒤 소설화 만료 정리로 작업 %d 건을 환불했다", expired)
