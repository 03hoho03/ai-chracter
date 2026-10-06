"""소설화 작업 실행 — 요청이 만든 작업 행(대기)을 백그라운드에서 돌려 성공으로 끝내거나 실패·환불한다.

**상태 흐름**: 요청이 `queued` + `heartbeat_at` 으로 행을 넣고 차감·커밋한 뒤 이 모듈로 띄운다 → `queued → running`
조건부 전이(받지 못하면 이미 정리된 작업이라 그냥 끝낸다) → 원문을 다시 읽고 입력을 만든다 → 모델 호출 → 결과 판정 →
성공 전이 + 저장, 또는 단일 환불 함수로 실패·환불.

**세션**: 요청 세션은 응답과 함께 닫히므로 쓰지 않고, 라우트가 넘긴 세션 팩토리로 단계마다 짧은 세션을 연다. 모델을
부르는 동안에는 세션을 쥐지 않는다 — 장 생성은 수 분까지 걸릴 수 있고, 그동안 커넥션을 붙잡으면 풀이 마른다.

**결과 저장 규칙**: 스트림 청크는 메모리에만 모은다(작업 행·heartbeat 에 본문을 싣지 않는다). 저장은 스트림이 예외
없이 끝까지 돈 뒤에만 한다 — 루프 안이나 `finally` 에서 저장하면 잘린 묶음이 저장된다. 중간에 끊지도 않는다(끊으면
잘림·빈 본문 판정과 사용량 기록이 일어나지 않는다). 모은 출력은 구분자 형식으로 읽어 화로 나눈다(`output.py`). 성공
저장은 **사용자 행 잠금 → 작업 상태 전이**를 먼저 하고 묶음·화·개정을 나중에 넣는다 — 전이가 행을 받지 못하면(만료
정리가 먼저 실패·환불했거나 소설 삭제가 작업 행을 지웠으면) 결과를 버린다.

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

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from api.core import clover
from api.core.config import settings
from api.core.sentry import capture_dependency_failure
from api.db.models.novel import (
    Novel,
    NovelBatch,
    NovelChapter,
    NovelChapterCharacter,
    NovelChapterRevision,
    NovelCharacter,
    NovelJob,
    NovelJobFailureCode,
)
from api.llm.client import (
    LLMCallContext,
    LLMClient,
    LLMClientError,
    LLMEmptyResponseError,
    LLMPolicyViolationError,
    LLMTruncatedError,
)
from api.novelize.billing import (
    ACTIVE_JOB_STATUSES,
    _lock_user,
    chapter_job_model,
    refund_job,
    shortfall_refund,
    transition_job,
)
from api.novelize.deletion import erase_stale_ai_edit_previews
from api.novelize.inputs import (
    ChapterInput,
    SourceChangedError,
    build_chapter_input,
    build_revise_input,
    current_revision,
    next_ordinal,
    regenerate_batch,
)
from api.novelize.output import MalformedOutputError, ParsedBatch, ParsedEpisode, parse_batch_output
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
            if job.kind == "ai_edit":
                usage = LLMCallContext(call_site="novelize_revise", user_id=job.user_id, room_id=novel.chat_room_id)
            else:
                # 작업에 적힌 모델 그대로다. 허용은 과금할 때 판정했고 여기서 다시 보지 않는다 — 그 사이 허용이 회수됐다고
                # 기본 모델로 바꾸면 상위 모델 값을 내고 다른 모델의 글을 받는다. 프롬프트 세트는 모델과 무관하게 기본
                # 모델 세트다(`build_chapter_input`). call site 를 바꾸지 않는다 — 상위 모델을 Bedrock 으로 보내는
                # 라우팅이 이 call site 로 고른다.
                usage = LLMCallContext(
                    call_site="novelize_chapter",
                    user_id=job.user_id,
                    room_id=novel.chat_room_id,
                    model=chapter_job_model(job),
                )
            kind = job.kind
        # 여기서부터 모델 호출 — 세션을 닫은 뒤다.
        if kind == "ai_edit":
            result_text = await _revise(llm_client, revise.prompt.prompt, revise.prompt.system_instruction, usage)
            body = _assemble_revision(revise.paragraphs, revise.first_index, revise.last_index, result_text)
            await _save_ai_edit(session_factory, job_id, body)
        else:
            batch = await _generate_batch(llm_client, chapter_input, usage)
            await _save_batch(session_factory, job_id, chapter_input, batch)
    finally:
        heartbeat.cancel()


async def _generate_batch(llm_client: LLMClient, chapter_input: ChapterInput, usage: LLMCallContext) -> ParsedBatch:
    """모델을 불러 묶음 출력을 받고 화로 나눈다. 판정 순서는 형식 → 화마다 본문 후처리 → 거절 → 최소 길이다. 후처리가
    빈 줄을 접으므로 형식을 먼저 읽는다. 형식이 어긋났어도 출력 전체가 거절문이면 거절로 실패한다 — 모델은 거절할 때
    형식을 지키지 않고, 사용자에게는 "형식 오류"보다 "거절"이 맞는 안내다.

    화 수는 여기서 판정하지 않는다. 생성은 목표보다 적어도 성공(모자란 몫 환불)이고 많아도 받아들이며, 다시 만들기의
    화 수 불일치는 저장이 묶음의 화를 잠근 뒤 판정한다."""
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
    raw = "".join(chunks)
    try:
        parsed = parse_batch_output(raw)
    except MalformedOutputError as exc:
        _judge(split_paragraphs(clean_chapter_body(raw)))
        logger.warning("소설화 묶음 출력이 형식에 맞지 않는다: %s", exc)
        raise _JobFailedError("malformed") from exc
    episodes: list[ParsedEpisode] = []
    for episode in parsed.episodes:
        body = clean_chapter_body(episode.body)
        _judge(split_paragraphs(body))
        if len(body) < settings.novelize_min_chapter_chars:
            raise _JobFailedError("malformed")
        episodes.append(
            ParsedEpisode(title=episode.title, summary=episode.summary, characters=episode.characters, body=body)
        )
    return ParsedBatch(novel_title=parsed.novel_title, episodes=tuple(episodes))


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
    문장으로 써서 전이가 행을 받지 못하면 결과도 남지 않는다.

    모델을 부르는 동안 사용자가 그 장을 고쳤으면(기준 개정이 이제 현재가 아니면) 결과는 적용할 수 없다. 쓸 수 없는
    미리보기에 과금하지 않도록 성공으로 저장하지 않고 `source_changed` 로 실패·환불한다.

    순서는 작업 행(성공 전이) → 장 행 잠금 → 현재 개정 확인이다. 장 행을 직접 수정·되돌리기·적용과 같은 잠금으로
    잡아야 확인과 커밋 사이에 새 개정이 끼지 못한다 — 잠그지 않고 읽기만 하면, 확인 직후 커밋된 새 개정 쪽의 낡은
    미리보기 비우기가 아직 커밋 전인 이 행(실행 중으로 보인다)을 지나쳐 낡은 결과가 성공으로 남는다. 저쪽이 장을 먼저
    잡았으면 이쪽은 그 커밋을 기다렸다가 새 개정을 보고 실패하고, 이쪽이 먼저 잡았으면 저쪽은 이 커밋 뒤에 개정을
    쌓고 그 뒤의 비우기가 이 결과를 본다. 장보다 작업 행을 먼저 잡는 것은 소설 삭제와 같은 순서라서다 — 삭제는 진행 중
    작업을 환불하며 작업 행을 쥔 채 장 행을 잠그므로, 이쪽이 장을 쥔 채 작업 행을 기다리면 서로를 기다린다.
    환불은 롤백해 잠금을 모두 놓은 뒤에 한다 — 환불은 사용자 행부터 잠그므로 작업 행을 쥔 채 부르면 사용자 → 작업
    순서를 거스른다."""
    async with session_factory() as db:
        saved = await transition_job(
            db,
            job_id=job_id,
            expected=("running",),
            values={"status": "succeeded", "result_text": body, "finished_at": func.now()},
        )
        if saved is None:
            await db.rollback()
            return
        chapter_id, base_revision_id = (
            await db.execute(select(NovelJob.chapter_id, NovelJob.base_revision_id).where(NovelJob.id == job_id))
        ).one()
        current = None
        if (
            chapter_id is not None
            and await db.scalar(
                select(NovelChapter.id).where(NovelChapter.id == chapter_id).with_for_update(key_share=True)
            )
            is not None
        ):
            current = await current_revision(db, chapter_id)
        if current is None or current.id != base_revision_id:
            await db.rollback()
            raise _JobFailedError("source_changed")
        await db.commit()


async def _save_batch(
    session_factory: SessionFactory, job_id: uuid.UUID, chapter_input: ChapterInput, batch: ParsedBatch
) -> None:
    """묶음 결과 저장. 한 트랜잭션에서 사용자 행 잠금 → 성공 전이 → 묶음·화·개정 → 인물·등장 연결 → 소설 제목 → 모자란
    화 환불이다.

    사용자 행을 먼저 잡는 이유는 모자란 화 환불이 사용자 행을 고치기 때문이다(`billing.py` 의 락 순서). 탈퇴가 사용자
    행을 쥔 채 작업을 지우는 중이면 여기서 기다렸다가, 탈퇴가 끝난 뒤 사용자나 작업 행이 없어 결과를 버린다. 만료
    정리와 겹쳐도 둘 다 사용자 행에서 줄을 서고 조건부 전이라 한쪽만 작업을 끝낸다.

    생성은 새 묶음 하나와 화 n 행을 넣는다(화마다 묶음 구간의 사본, 화 번호는 이어서). 목표보다 적게 냈으면 모자란
    화만큼 돌려주고, 많이 냈으면 추가로 받지 않고 모두 넣는다. 다시 만들기는 묶음의 화를 잠그고 화 수가 지금 화 수와
    같아야 한다 — 다르면 롤백한 뒤 `episode_count_mismatch` 로 실패·환불한다(화 행을 그대로 두어야 읽은 위치·작가의
    말·개정 이력이 산다). 같으면 화마다 새 개정을 쌓고 화 제목·요약·등장 인물을 바꾼다.

    작업 행에는 묶음과 화 하나를 남긴다 — 생성은 첫 화, 다시 만들기는 요청이 가리킨 화(없으면 첫 화)와 그 화의 새
    개정이다. 작업 폴링 화면이 이 화로 이동한다."""
    async with session_factory() as db:
        user_id = await db.scalar(select(NovelJob.user_id).where(NovelJob.id == job_id))
        if user_id is None or not await _lock_user(db, user_id):
            await db.rollback()
            return
        moved = await transition_job(
            db, job_id=job_id, expected=("running",), values={"status": "succeeded", "finished_at": func.now()}
        )
        if moved is None:
            await db.rollback()
            return
        job = await db.get(NovelJob, job_id)
        assert job is not None  # 방금 전이가 행을 받았고 같은 트랜잭션이 그 행을 잠그고 있다
        if job.kind == "chapter_regenerate":
            saved = await _save_regenerated(db, job, batch)
            if saved is None:
                await db.rollback()
                raise _JobFailedError("episode_count_mismatch")
            batch_id, chapters, revisions = saved
        else:
            batch_id, chapters, revisions = await _save_generated(db, job, chapter_input, batch)
        await _link_characters(db, job.novel_id, chapters, batch.episodes)
        if chapter_input.writes_novel_title and batch.novel_title:
            # 사용자가 그사이 제목을 고쳤으면 덮지 않는다 — 조건을 문장에 걸어 읽고 쓰는 사이에 끼어들 틈이 없다.
            await db.execute(
                update(Novel)
                .where(Novel.id == job.novel_id, Novel.title_edited_at.is_(None))
                .values(title=batch.novel_title)
            )
        target_index = next((i for i, c in enumerate(chapters) if c.id == job.chapter_id), 0)
        await db.execute(
            update(NovelJob)
            .where(NovelJob.id == job_id)
            .values(
                batch_id=batch_id,
                chapter_id=chapters[target_index].id,
                result_revision_id=revisions[target_index].id,
            )
        )
        refund = shortfall_refund(
            charged_amount=moved.charged_amount,
            target=moved.episode_count_target or 1,
            delivered=len(batch.episodes),
        )
        if refund > 0:
            await db.execute(
                update(NovelJob).where(NovelJob.id == job_id).values(refunded_at=func.now(), refunded_amount=refund)
            )
            await clover.grant(db, user_id=user_id, amount=refund, kind="novelize_refund")
        await db.execute(update(Novel).where(Novel.id == job.novel_id).values(updated_at=func.now()))
        await db.commit()
        if job.kind == "chapter_regenerate":
            # 다시 만든 결과가 화마다 새 현재 개정이 되면 옛 개정을 기준으로 한 미리보기는 적용할 수 없다. 화를 잠근
            # 트랜잭션을 끝낸 뒤에 비운다(화를 쥔 채 작업 행을 고치면 적용과 교착한다).
            for chapter in chapters:
                await erase_stale_ai_edit_previews(db, chapter.id)
            await db.commit()


async def _save_generated(
    db: AsyncSession, job: NovelJob, chapter_input: ChapterInput, batch: ParsedBatch
) -> tuple[uuid.UUID, list[NovelChapter], list[NovelChapterRevision]]:
    assert (
        job.start_message_id is not None
        and job.start_message_created_at is not None
        and job.end_message_id is not None
        and job.end_message_created_at is not None
    )
    segment = {
        "start_message_id": job.start_message_id,
        "start_message_created_at": job.start_message_created_at,
        "end_message_id": job.end_message_id,
        "end_message_created_at": job.end_message_created_at,
        "assistant_message_count": chapter_input.assistant_count,
        "source_hash": chapter_input.source_hash,
    }
    batch_ordinal = await db.scalar(
        select(func.coalesce(func.max(NovelBatch.ordinal), 0)).where(NovelBatch.novel_id == job.novel_id)
    )
    row = NovelBatch(
        novel_id=job.novel_id,
        ordinal=int(batch_ordinal or 0) + 1,
        target_episode_count=job.episode_count_target or 1,
        **segment,
    )
    db.add(row)
    await db.flush()
    first_ordinal = await next_ordinal(db, job.novel_id)
    chapters = [
        NovelChapter(
            novel_id=job.novel_id,
            ordinal=first_ordinal + index,
            batch_id=row.id,
            episode_index=index,
            title=episode.title,
            summary=episode.summary,
            **segment,
        )
        for index, episode in enumerate(batch.episodes)
    ]
    db.add_all(chapters)
    await db.flush()
    revisions = [
        NovelChapterRevision(chapter_id=chapter.id, revision_no=1, body=episode.body, source="generate")
        for chapter, episode in zip(chapters, batch.episodes, strict=True)
    ]
    db.add_all(revisions)
    await db.flush()
    return row.id, chapters, revisions


async def _save_regenerated(
    db: AsyncSession, job: NovelJob, batch: ParsedBatch
) -> tuple[uuid.UUID, list[NovelChapter], list[NovelChapterRevision]] | None:
    """묶음의 화마다 새 개정을 쌓는다. 화 수가 출력과 다르면 아무것도 쓰지 않고 None.

    화 행을 `FOR KEY SHARE` 로 잠근다 — 직접 수정·되돌리기도 화 행을 먼저 잠그고 다음 개정 번호를 쓰므로 같은 번호를
    동시에 쓰지 않게 줄을 선다."""
    target = await regenerate_batch(db, job)
    if target is None:
        # 다시 만들 묶음이 지워졌다 — 묶음 삭제는 진행 중 작업이 있으면 거절하므로 옛 판 코드가 지운 경우뿐이다.
        return None
    chapters = list(
        (
            await db.scalars(
                select(NovelChapter)
                .where(NovelChapter.batch_id == target.id)
                .order_by(NovelChapter.episode_index, NovelChapter.ordinal)
                .with_for_update(key_share=True)
            )
        ).all()
    )
    if len(chapters) != len(batch.episodes):
        return None
    revisions: list[NovelChapterRevision] = []
    for chapter, episode in zip(chapters, batch.episodes, strict=True):
        latest = await current_revision(db, chapter.id)
        revisions.append(
            NovelChapterRevision(
                chapter_id=chapter.id,
                revision_no=(latest.revision_no if latest else 0) + 1,
                body=episode.body,
                source="regenerate",
            )
        )
        chapter.title = episode.title
        chapter.summary = episode.summary
    db.add_all(revisions)
    await db.flush()
    return target.id, chapters, revisions


async def _link_characters(
    db: AsyncSession, novel_id: uuid.UUID, chapters: Sequence[NovelChapter], episodes: Sequence[ParsedEpisode]
) -> None:
    """화마다 출력이 적은 등장 인물을 인물 카드에 붙인다. 이름이나 별칭이 같은 카드가 있으면 그 카드, 없으면 새 카드다.
    다시 만들기는 그 화의 옛 연결을 지우고 새로 붙인다(연결은 본문과 함께 나온 사실이다). 카드는 지우지 않는다 — 사용자가
    메모를 적은 카드일 수 있다.

    사용자 행 잠금 아래에서 부른다. 이름 ∪ 별칭이 소설 안에서 겹치지 않는 것은 DB 가 아니라 코드가 지키므로, 카드를 고치는
    다른 경로도 같은 잠금을 잡아야 같은 이름으로 카드가 둘 생기지 않는다."""
    cards = (await db.scalars(select(NovelCharacter).where(NovelCharacter.novel_id == novel_id))).all()
    by_name: dict[str, NovelCharacter] = {}
    for card in cards:
        by_name[card.name] = card
        for alias in card.aliases:
            by_name.setdefault(alias, card)
    await db.execute(
        delete(NovelChapterCharacter).where(NovelChapterCharacter.chapter_id.in_([c.id for c in chapters]))
    )
    for chapter, episode in zip(chapters, episodes, strict=True):
        linked: set[uuid.UUID] = set()
        for name in episode.characters:
            found = by_name.get(name)
            if found is None:
                found = NovelCharacter(novel_id=novel_id, name=name)
                db.add(found)
                await db.flush()
                by_name[name] = found
            if found.id not in linked:
                linked.add(found.id)
                db.add(NovelChapterCharacter(chapter_id=chapter.id, character_id=found.id))
    await db.flush()


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
