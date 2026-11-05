"""슬롯 작업 하나 실행 — 받기 → 입력 → 렌더 → 캐시 → 호출 → 검증 → 저장, 실패면 재시도 또는 실패.

모델을 기다리는 동안 DB 커넥션을 쥐지 않는다 — 받기·입력 읽기·저장이 각자 짧은 세션이다. 저장은 받은 행(`running`)에만
되므로, 그 사이 화가 지워져 작업 행이 사라지면 결과는 0행 UPDATE 로 버려진다. 이미 받은 작업은 그 사이 확정이
밀려나도(`stale`) 작업 행이 그대로라 제안을 저장한다 — 같은 개정을 다시 확정하면 그 제안을 추출 캐시로 쓴다.

슬롯의 검증을 지난 제안에서 코어가 개체로 풀어야 하는 이름(지식의 앎 주체, 명제의 주어, 대상이 개체인 종류의 대상)이 정규화 뒤
비는 항목은 저장 전에 버리고 `dropped` 에 센다 — 그런 항목은 행의 주어도 안정 키도 만들 수 없다. 정규화한 이름이 개체 이름
길이 상한을 넘으면 연결이 그 이름으로 개체를 만들다 CHECK 에 걸려 확정 전체가 실패하므로 저장 전에 걸러 낸다. 그 이름이 위의
개체 하나로 푸는 칸에 있으면 항목을 버리고, 그 밖의 이름 칸(사건의 등장·언급 인물 같은 이름 목록)에 있으면 그 이름만 빼고
항목은 남긴다 — 이름 하나 때문에 사건이 통째로 빠지면 사건이 덜 잡힌 것처럼 보인다. 뺀 이름도 이름 수로 `dropped` 에 센다.
이름 목록 둘을 같은 차례로 짝지어 저장하는 슬롯(사건의 행동)은 코어가 한쪽 칸에서만 빼면 짝이 어긋나므로, 그런 짝은 슬롯이
검증에서 먼저 뺀다. 명제의 주어 이름(`names["subject"]`)의 개체 종류가 명제의 주어 종류와 다른 항목도 버린다 — 행과 안정 키는
이름의 종류로 개체를 잇는데, 같은 명제를 내는 다른 슬롯은 명제의 종류로 이어 둘의 키가 갈린다. 슬롯 계약이 둘을 같게 만들라고
하지만 코어는 그 약속에 기대지 않고 확인한다 — assert 로 막으면 슬롯 하나의 실수로 확정 전체가 실패하므로 그 항목만 버린다.
출력 전체가 아니라 그 항목이나 그 이름만 버린다.

추출 캐시: 같은 소설에서 슬롯·어댑터·문안 세트·출력 스키마·검증 규칙 판이 같고 본문 해시·블록 id 해시·슬롯의 힌트가
아닌 렌더 값·입력이 읽은 채팅 기억 행의 방·행 id·입력이 읽은 원작의 버전 id·노트 id 가 같은 앞 작업이 성공해 있으면 그 제안을
복사하고 호출하지 않는다. 힌트(아는 개체 따위 정본 상태에서 오는 값)는 다른 화가 커밋될 때마다 바뀌므로 열쇠에서 뺀다. 블록 id
해시가 열쇠에 드는 이유는 제안이 블록 id 로 저장돼 있어서다 — 본문이 같아도 블록 id 가 다른 개정에는 다시 쓸 수 없다. 채팅 기억
행 id 도 같은 이유다 — 제안의 플레이 근거가 행 id 로 저장돼 있는데 렌더 글에는 id 가 없어, 되감기 뒤 같은 사실이 같은 글의 새
행으로 다시 쓰이면 글만으로는 열쇠가 같아 지워진 행을 가리키는 제안을 재사용하게 된다(그 근거는 태어날 때부터 소실로 읽힌다).
원작 버전 id·노트 id 도 같다 — 원작 근거가 그 id 로 저장되는데 렌더 글에는 표지(`S`·`K1`)만 있어, 같은 글의 새 버전·새 노트로
바뀌면 글만으로는 이번 확정이 읽지 않은 버전·노트를 가리키는 제안을 재사용하게 된다."""

import hashlib
import json
import logging
import uuid
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from pydantic import BaseModel
from sqlalchemy import exists, func, select, type_coerce, update
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from api.chat.prompt_builder import PromptRenderError
from api.db.models.novel import Novel, NovelChapter
from api.db.models.novel_bible import ENTITY_NAME_MAX, NovelBibleCommit, NovelBibleJob
from api.novel_bible.core.contracts import AdapterCallError, AdapterResolver, Registry, Slot
from api.novel_bible.core.keys import TARGETED_KINDS, normalize_name
from api.novel_bible.core.render import RequiredValueEmptyError, render
from api.novel_bible.core.types import CommitRef, Proposal, RenderedPrompt
from api.novel_bible.core.views import CommitView, source_ref_of
from api.novel_bible.ids import JobFailure, SlotId

logger = logging.getLogger(__name__)

SessionFactory = async_sessionmaker[AsyncSession]

MAX_ATTEMPTS = 3
RETRY_DELAY = timedelta(seconds=30)
# 같은 입력으로 다시 부르면 나을 수 있는 실패. 문안 없음·입력 과다·안전 차단은 다시 불러도 같다.
_RETRYABLE: frozenset[JobFailure] = frozenset(
    {"schema_invalid", "truncated", "empty", "llm_error", "rate_limited", "cancelled", "internal", "expired"}
)
# 코어가 풀어야 하는 이름이 비어 버린 항목의 `dropped` 사유.
EMPTY_NAME = "empty_name"
# 명제의 주어 이름의 개체 종류가 명제의 주어 종류와 다른 항목의 `dropped` 사유.
SUBJECT_KIND_MISMATCH = "subject_kind_mismatch"
# 코어가 개체 하나로 풀어야 하는 칸의 이름이 정규화 뒤 개체 이름 길이 상한을 넘는 항목의 `dropped` 사유.
NAME_TOO_LONG = "name_too_long"
# 이름 목록 칸에서 상한을 넘어 뺀 이름의 `dropped` 사유 — 항목이 아니라 뺀 이름 수를 센다.
LISTED_NAME_TOO_LONG = "listed_name_too_long"
# 추출 캐시 열쇠에 드는 검증 규칙의 판. 캐시는 검증을 마친 제안을 다시 검증하지 않고 복사하므로, 슬롯 검증이나 코어의 거르기
# (근거 인용 찾기·이름 거르기) 규칙을 바꾸면 이 값을 올려 옛 규칙으로 만든 제안을 다시 쓰지 않게 한다. 이 값이 열쇠에 들기 전의
# 작업은 열쇠 꼴이 달라 어느 판과도 맞지 않는다.
_VALIDATION_VERSION = 3


async def commit_ref(session: AsyncSession, commit: NovelBibleCommit) -> CommitRef:
    assert commit.chapter_id is not None and commit.chapter_revision_id is not None  # 화 확정만 있다
    ordinal, content_type = (
        await session.execute(
            select(NovelChapter.ordinal, Novel.content_type)
            .join(Novel, Novel.id == NovelChapter.novel_id)
            .where(NovelChapter.id == commit.chapter_id)
        )
    ).one()
    return CommitRef(
        commit_id=commit.id,
        novel_id=commit.novel_id,
        chapter_id=commit.chapter_id,
        chapter_revision_id=commit.chapter_revision_id,
        chapter_ordinal=ordinal,
        scope="story" if content_type == "story" else "character",
    )


def name_too_long(name: str) -> bool:
    return len(normalize_name(name)) > ENTITY_NAME_MAX


def drop_unlinkable(proposal: Proposal) -> Proposal:
    kept = []
    dropped = dict(proposal.dropped)
    for draft in proposal.items:
        needed = ["knower"] if draft.table == "knowledge" else []
        if draft.proposition is not None:
            needed.append("subject")
            if draft.proposition.kind in TARGETED_KINDS:
                needed.append("value")
        if not all(any(normalize_name(name.name) for name in draft.names.get(field, ())) for field in needed):
            reason = EMPTY_NAME
        elif draft.proposition is not None and any(
            name.kind != draft.proposition.subject_kind for name in draft.names["subject"]
        ):
            reason = SUBJECT_KIND_MISMATCH
        elif any(name_too_long(name.name) for field in needed for name in draft.names.get(field, ())):
            reason = NAME_TOO_LONG
        else:
            listed = {
                field: names if field in needed else tuple(name for name in names if not name_too_long(name.name))
                for field, names in draft.names.items()
            }
            removed = sum(len(names) - len(listed[field]) for field, names in draft.names.items())
            if removed:
                dropped[LISTED_NAME_TOO_LONG] = dropped.get(LISTED_NAME_TOO_LONG, 0) + removed
                draft = draft.model_copy(update={"names": listed})
            kept.append(draft)
            continue
        dropped[reason] = dropped.get(reason, 0) + 1
    return Proposal(items=tuple(kept), dropped=dropped)


def _digest(parts: list[Any]) -> str:
    return hashlib.sha256(json.dumps(parts, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class _Prepared:
    slot_input: BaseModel
    prompt: RenderedPrompt
    adapter_id: str
    cache_key: str
    input_hash: str
    cached: tuple[uuid.UUID, dict[str, Any]] | None
    too_large: bool


async def _claim(
    factory: SessionFactory, novel_id: uuid.UUID | None
) -> tuple[uuid.UUID, uuid.UUID, SlotId, int] | None:
    """대기 작업 하나를 받는다 — 작업 행 → 확정 행 순으로 잠근다(삭제 경로와 같은 순서)."""
    async with factory() as session, session.begin():
        candidate = (
            select(NovelBibleJob.id)
            .join(NovelBibleCommit, NovelBibleCommit.id == NovelBibleJob.commit_id)
            .where(
                NovelBibleJob.status == "queued",
                NovelBibleJob.available_at <= func.now(),
                NovelBibleCommit.status.in_(("pending", "extracting")),
            )
            .order_by(NovelBibleJob.available_at, NovelBibleJob.created_at)
            .limit(1)
            .with_for_update(of=NovelBibleJob, skip_locked=True)
        )
        if novel_id is not None:
            candidate = candidate.where(NovelBibleJob.novel_id == novel_id)
        job_id = await session.scalar(candidate)
        if job_id is None:
            return None
        live_commit = exists().where(
            NovelBibleCommit.id == NovelBibleJob.commit_id, NovelBibleCommit.status.in_(("pending", "extracting"))
        )
        claimed = (
            await session.execute(
                update(NovelBibleJob)
                .where(NovelBibleJob.id == job_id, NovelBibleJob.status == "queued", live_commit)
                .values(status="running", attempts=NovelBibleJob.attempts + 1, claimed_at=func.now())
                .returning(NovelBibleJob.commit_id, NovelBibleJob.slot, NovelBibleJob.attempts)
            )
        ).one_or_none()
        if claimed is None:
            return None
        await session.execute(
            update(NovelBibleCommit)
            .where(NovelBibleCommit.id == claimed.commit_id, NovelBibleCommit.status == "pending")
            .values(status="extracting")
        )
        return job_id, claimed.commit_id, claimed.slot, claimed.attempts


async def _prepare(
    factory: SessionFactory, registry: Registry, slot: Slot, resolver: AdapterResolver, job_id: uuid.UUID,
    commit_id: uuid.UUID,
) -> _Prepared | None:
    async with factory() as session:
        commit = await session.get(NovelBibleCommit, commit_id)
        if commit is None:
            return None
        view = CommitView(
            session, registry, await commit_ref(session, commit), source_ref_of(commit), commit.chat_room_id
        )
        slot_input = await slot.build_input(session, view)
        values = slot.prompt_values(slot_input)
        adapter = resolver(slot.operation)
        source = await adapter.prompt_source(session)
        prompt = render(source, channel=slot.channel, scope=view.commit.scope, values=values)
        schema_name = slot.output_schema.__name__
        cache_key = _digest(
            [
                commit.content_hash, commit.block_ids_hash, slot.id, adapter.id, str(source.prompt_set_id), schema_name,
                _VALIDATION_VERSION,
                {name: value for name, value in values.items() if name not in slot.hint_values},
                [[str(fact.chat_room_id), str(fact.chat_memory_fact_id)] for fact in view.served_play_facts],
                [str(canon.ref.content_version_id), [str(note_id) for note_id in canon.keyword_notes]]
                if (canon := view.served_source_canon) is not None
                else None,
            ]
        )
        input_hash = _digest(
            [prompt.system_instruction, prompt.prompt, adapter.id, str(source.prompt_set_id), schema_name]
        )
        cached = (
            await session.execute(
                select(NovelBibleJob.id, NovelBibleJob.proposal)
                .where(
                    NovelBibleJob.novel_id == commit.novel_id,
                    NovelBibleJob.slot == slot.id,
                    NovelBibleJob.cache_key == cache_key,
                    NovelBibleJob.status == "succeeded",
                    NovelBibleJob.id != job_id,
                )
                .order_by(NovelBibleJob.finished_at.desc())
                .limit(1)
            )
        ).one_or_none()
        too_large = len(prompt.system_instruction) + len(prompt.prompt) > adapter.capabilities.max_input_chars
        return _Prepared(
            slot_input=slot_input,
            prompt=prompt,
            adapter_id=adapter.id,
            cache_key=cache_key,
            input_hash=input_hash,
            cached=(cached.id, dict(cached.proposal)) if cached is not None and cached.proposal is not None else None,
            too_large=too_large,
        )


async def _succeed(
    factory: SessionFactory, job_id: uuid.UUID, prepared: _Prepared, proposal: dict[str, Any],
    records: list[dict[str, Any]], reused_from: uuid.UUID | None,
) -> None:
    async with factory() as session, session.begin():
        await session.execute(
            update(NovelBibleJob)
            .where(NovelBibleJob.id == job_id, NovelBibleJob.status == "running")
            .values(
                status="succeeded",
                proposal=proposal,
                input_hash=prepared.input_hash,
                cache_key=prepared.cache_key,
                adapter_id=prepared.adapter_id,
                prompt_set_id=prepared.prompt.prompt_set_id,
                reused_from_job_id=reused_from,
                llm_calls=NovelBibleJob.llm_calls.op("||")(type_coerce(records, JSONB)),
                failure_code=None,
                finished_at=func.now(),
            )
        )


async def _fail(
    factory: SessionFactory, job_id: uuid.UUID, attempts: int, code: JobFailure, *, retry: bool,
    records: list[dict[str, Any]],
) -> None:
    calls = NovelBibleJob.llm_calls.op("||")(type_coerce(records, JSONB))
    running = (NovelBibleJob.id == job_id, NovelBibleJob.status == "running")
    async with factory() as session, session.begin():
        if retry and attempts < MAX_ATTEMPTS:
            await session.execute(
                update(NovelBibleJob)
                .where(*running)
                .values(
                    status="queued", failure_code=code, llm_calls=calls,
                    available_at=func.now() + RETRY_DELAY * attempts,
                )
            )
        else:
            await session.execute(
                update(NovelBibleJob)
                .where(*running)
                .values(status="failed", failure_code=code, llm_calls=calls, finished_at=func.now())
            )


async def run_next_job(
    factory: SessionFactory, registry: Registry, resolver: AdapterResolver, *, novel_id: uuid.UUID | None = None
) -> bool:
    """대기 작업 하나를 끝 상태(또는 재시도 대기)까지 돌린다. 받은 작업이 없으면 거짓."""
    claimed = await _claim(factory, novel_id)
    if claimed is None:
        return False
    job_id, commit_id, slot_id, attempts = claimed
    slot = registry.extracting.get(slot_id)
    records: list[dict[str, Any]] = []
    if slot is None:
        # 확정을 받은 뒤 등록부에서 빠진 슬롯(이미지 교체) — 다시 돌려도 같다.
        await _fail(factory, job_id, attempts, "internal", retry=False, records=records)
        return True
    try:
        prepared = await _prepare(factory, registry, slot, resolver, job_id, commit_id)
        if prepared is None:
            return True
        if prepared.cached is not None:
            reused_from, proposal = prepared.cached
            await _succeed(factory, job_id, prepared, proposal, records, reused_from)
            return True
        if prepared.too_large:
            await _fail(factory, job_id, attempts, "input_too_large", retry=False, records=records)
            return True
        output = await resolver(slot.operation).structured(
            prepared.prompt, slot.output_schema, records=records, stage=slot.operation
        )
        validated = drop_unlinkable(slot.validate(prepared.slot_input, output))
        await _succeed(factory, job_id, prepared, validated.model_dump(mode="json"), records, None)
    except AdapterCallError as error:
        await _fail(factory, job_id, attempts, error.code, retry=error.retryable and error.code in _RETRYABLE,
                    records=records)
    except RequiredValueEmptyError as error:
        # 문안은 있고 입력(빈 원고 따위)이 빈 것이다. 실패 사유 칸은 DB CHECK 가 묶은 값이라 새 사유를 두려면 마이그레이션이
        # 들어야 해서 문안 없음과 같은 사유로 남기고, 로그가 빈 값의 섹션을 적어 문안 누락과 가른다. 다시 돌려도 같은 입력이라
        # 재시도하지 않는다.
        logger.warning(
            "정본 기억 작업 %s 의 필수 값이 비었다 — 문안이 아니라 입력 문제다(채널 %s, 섹션 %s, 빈 값 %s)",
            job_id, slot.channel, error.section, ", ".join(error.names),
        )
        await _fail(factory, job_id, attempts, "prompt_missing", retry=False, records=records)
    except PromptRenderError:
        logger.warning("정본 기억 작업 %s 의 문안이 없다(채널 %s)", job_id, slot.channel, exc_info=True)
        await _fail(factory, job_id, attempts, "prompt_missing", retry=False, records=records)
    except Exception:
        logger.exception("정본 기억 작업 %s 실패", job_id)
        await _fail(factory, job_id, attempts, "internal", retry=True, records=records)
    return True
