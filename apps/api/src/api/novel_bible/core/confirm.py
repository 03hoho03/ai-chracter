"""정본 기억 확정 입구 — 화 개정 하나를 확정 행 하나와 슬롯마다 작업 행 하나로 받는다.

아무것도 하지 않는 경우는 하나뿐이다: 그 화의 현재 확정 개정(그 화의 확정 중 가장 높은 리비전을 낸 것)과 같은 개정이 다시
들어왔을 때. 진행 중 확정과 같은 개정이 다시 들어와도 새 확정이고(앞 것은 `stale`), 되돌리기·삽화 개정처럼 본문이 같은
개정도 개정 id 가 다르면 새 확정이다(추출은 캐시로 다시 쓴다).

잠금 순서는 화 행(`FOR KEY SHARE`) → 같은 화의 진행 중 확정 행(UPDATE) → INSERT 다 — 커밋 트랜잭션·삭제 경로와 같은 순서라
교착이 없다. 화 행을 먼저 잡으므로 숨긴 소설 정리(화 행을 `FOR UPDATE` 로 잡고 정본 기억을 지운 뒤 숨김 시각을 쓴다)와 겹쳐도,
정리가 먼저면 이쪽이 기다렸다가 숨김 시각을 보고 거절하고, 이쪽이 먼저면 정리가 기다렸다가 새 확정까지 지운다."""

import hashlib
import uuid
from dataclasses import dataclass

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.models.novel import Novel, NovelChapter, NovelChapterRevision
from api.db.models.novel_bible import NovelBibleCommit, NovelBibleJob, NovelBibleRevision
from api.novel_bible.core.contracts import Registry
from api.novel_bible.ids import ActorKind, CommitStatus, SlotId

CANON = "canon"
IN_FLIGHT: tuple[CommitStatus, ...] = ("pending", "extracting", "linking", "checking")
_IN_FLIGHT_INDEX = "ux_novel_bible_commits_in_flight"


@dataclass(frozen=True)
class Actor:
    kind: ActorKind
    id: uuid.UUID | None = None


@dataclass(frozen=True)
class ConfirmResult:
    commit_id: uuid.UUID
    status: CommitStatus
    created: bool  # 거짓 = 같은 개정이 이미 그 화의 현재 확정이라 아무것도 하지 않음


class ConfirmTargetNotFoundError(Exception):
    """소설·화·개정이 서로 맞지 않거나, 소설이 숨겨졌다(작가 전용 데이터를 지운 소설이라 정본 기억도 쓰지 않는다)."""


class ConfirmConflictError(Exception):
    """같은 화로 동시에 들어온 다른 입구에 두 번 졌다."""


def block_ids_hash(block_ids: list[uuid.UUID]) -> str:
    """개정의 블록 id 를 순서대로 줄바꿈으로 이은 글의 sha256 — 본문이 같고 블록 id 만 다른 개정을 가른다."""
    return hashlib.sha256("\n".join(str(block_id) for block_id in block_ids).encode("utf-8")).hexdigest()


async def _current_confirmed(
    session: AsyncSession, novel_id: uuid.UUID, chapter_id: uuid.UUID
) -> tuple[uuid.UUID, uuid.UUID] | None:
    """그 화의 현재 확정 — (확정 id, 확정한 개정 id). 리비전 번호는 지운 화의 번호가 다시 쓰일 수 있지만, 남아 있는 리비전
    끼리는 번호 순서가 넣은 순서다(새 번호는 늘 남은 것 중 최대 + 1)."""
    row = (
        await session.execute(
            select(NovelBibleCommit.id, NovelBibleCommit.chapter_revision_id)
            .join(NovelBibleRevision, NovelBibleRevision.commit_id == NovelBibleCommit.id)
            .where(
                NovelBibleRevision.novel_id == novel_id,
                NovelBibleRevision.branch == CANON,
                NovelBibleCommit.chapter_id == chapter_id,
            )
            .order_by(NovelBibleRevision.revision_no.desc())
            .limit(1)
        )
    ).one_or_none()
    if row is None or row.chapter_revision_id is None:
        return None
    return row.id, row.chapter_revision_id


async def confirm(
    session: AsyncSession,
    registry: Registry,
    *,
    novel_id: uuid.UUID,
    chapter_id: uuid.UUID,
    revision_id: uuid.UUID,
    actor: Actor,
    slots: frozenset[SlotId] | None = None,
) -> ConfirmResult:
    """`slots` 가 None 이면 등록부의 추출 슬롯 전부, 아니면 그중 `slots` 에 든 것만 작업을 만든다. 커밋은 호출부가 한다."""
    chapter = (
        await session.execute(
            select(NovelChapter.id).where(NovelChapter.id == chapter_id, NovelChapter.novel_id == novel_id)
            .with_for_update(read=True, key_share=True)
        )
    ).one_or_none()
    novel = (
        await session.execute(select(Novel.hidden_at, Novel.chat_room_id).where(Novel.id == novel_id))
    ).one_or_none()
    revision = await session.get(NovelChapterRevision, revision_id)
    if chapter is None or novel is None or novel.hidden_at is not None or revision is None:
        raise ConfirmTargetNotFoundError
    if revision.chapter_id != chapter_id:
        raise ConfirmTargetNotFoundError

    current = await _current_confirmed(session, novel_id, chapter_id)
    if current is not None and current[1] == revision_id:
        return ConfirmResult(commit_id=current[0], status="committed", created=False)

    source = await registry.source.resolve(session, novel_id) if registry.source is not None else None
    selected = [slot for slot_id, slot in registry.extracting.items() if slots is None or slot_id in slots]
    status: CommitStatus = "pending" if selected else "extracting"
    lost = False
    while True:
        try:
            async with session.begin_nested():
                # 같은 화로 동시에 들어온 다른 입구가 먼저 넣은 진행 중 확정이 있으면 부분 유니크 위반이 난다. 세이브포인트로
                # 되돌리고 한 번 더 — 이번에는 그 확정이 보여 stale 로 돌린 뒤 넣는다.
                await session.execute(
                    update(NovelBibleCommit)
                    .where(
                        NovelBibleCommit.novel_id == novel_id,
                        NovelBibleCommit.branch == CANON,
                        NovelBibleCommit.chapter_id == chapter_id,
                        NovelBibleCommit.status.in_(IN_FLIGHT),
                    )
                    .values(status="stale", finished_at=func.now())
                )
                commit = NovelBibleCommit(
                    novel_id=novel_id,
                    kind="chapter_confirm",
                    branch=CANON,
                    chapter_id=chapter_id,
                    chapter_revision_id=revision_id,
                    content_hash=revision.content_hash,
                    block_ids_hash=block_ids_hash(list(revision.block_ids)),
                    status=status,
                    source_content_version_id=source.content_version_id if source else None,
                    source_input_hash=source.input_hash if source else None,
                    chat_room_id=novel.chat_room_id,
                    actor_kind=actor.kind,
                    actor_id=actor.id,
                )
                session.add(commit)
                await session.flush()
                session.add_all(
                    [NovelBibleJob(novel_id=novel_id, commit_id=commit.id, slot=slot.id) for slot in selected]
                )
                await session.flush()
            return ConfirmResult(commit_id=commit.id, status=status, created=True)
        except IntegrityError as error:
            if _IN_FLIGHT_INDEX not in str(error.orig):
                raise
            if lost:
                raise ConfirmConflictError from error
            lost = True
