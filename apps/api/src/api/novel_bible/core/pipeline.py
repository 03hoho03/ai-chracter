"""준비된 확정 하나의 처리 — 연결 → 검사 → 커밋(머리 비교).

상태 전이는 모두 조건부 UPDATE 다(`WHERE status = 지금 상태`). 그 사이 같은 화에 새 확정이 들어와 이 확정이 `stale` 이 되거나
삭제 경로가 행을 지우면 다음 전이가 0행이 되어 처리가 멈춘다. 끝 상태(`committed`·`blocked`·`failed`·`stale`) 행은 다시 바뀌지
않는다.

커밋은 화 행(`FOR KEY SHARE`) → 확정 행(`FOR UPDATE`) 순으로 잡는다. 삭제 경로는 화 행을 `FOR UPDATE` 로 쥔 채 정본 기억 행을
지우므로, 커밋이 확정 행을 먼저 잡으면 항목 INSERT 의 FK 검사(화 행 키 공유 잠금)와 삭제 쪽의 확정 행 DELETE 가 서로를 기다린다.
화 행을 맨 앞에서 잡으면 두 쪽 순서가 같아진다 — 삭제가 먼저면 커밋이 기다렸다가 화가 없음을 보고 물러나고, 커밋이 먼저면
삭제가 기다렸다가 새로 커밋된 행까지 지운다.

머리 비교는 리비전 번호가 아니라 리비전 id 로 한다. 묶음 삭제가 머리 리비전을 지우면 그 번호를 다른 확정이 다시 얻을 수
있어, 번호로 비교하면 "그 사이 다른 확정이 커밋됐다"를 놓친다. 같은 머리를 동시에 읽은 두 커밋은 (소설, 가지, 번호) 유니크가
하나만 통과시킨다. 진 쪽은 새 머리를 기준으로 저장된 작업 제안을 그대로 다시 연결·검사한다(다시 추출하지 않는다)."""

import logging
import uuid
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import Exists, exists, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from api.db.models.novel import NovelChapter, NovelChapterRevision
from api.db.models.novel_bible import (
    NovelBibleAdaptationCandidate,
    NovelBibleCommit,
    NovelBibleEntity,
    NovelBibleEvidence,
    NovelBibleExpiration,
    NovelBibleFinding,
    NovelBibleJob,
    NovelBibleRevision,
)
from api.novel_bible.core.confirm import CANON, IN_FLIGHT
from api.novel_bible.core.contracts import AdapterResolver, Registry, Rule
from api.novel_bible.core.jobs import SessionFactory, commit_ref, run_next_job
from api.novel_bible.core.keys import normalize_name, proposition_key
from api.novel_bible.core.queries import assemble
from api.novel_bible.core.quotes import manuscript_evidence_verified
from api.novel_bible.core.types import (
    CommitRef,
    EventRow,
    FactRow,
    FindingDraft,
    ItemDraft,
    KnowledgeRow,
    LinkedItem,
    Manuscript,
    Proposal,
    RelationRow,
    RevisionRef,
)
from api.novel_bible.core.views import manuscript_of
from api.novel_bible.ids import CommitFailure, CommitStatus, EntityKind, ItemTable, SlotId

logger = logging.getLogger(__name__)

# 커밋 머리 비교에서 이만큼 지면 확정을 실패로 끝낸다.
CAS_LIMIT = 5
_REVISION_NUMBER_INDEX = "ux_novel_bible_revisions_novel_branch_no"
# 새 리비전의 앞 리비전 FK. 다른 화 묶음 삭제가 머리 리비전을 지우는 중이면 머리 비교는 아직 옛 머리를 보고 통과하고, 이 FK
# 검사가 삭제를 기다렸다가 위반이 된다 — 그 사이 머리가 바뀐 것이므로 머리 비교에서 진 것과 같이 다룬다.
_PARENT_REVISION_FK = "novel_bible_revisions_parent_revision_id_fkey"

Row = EventRow | RelationRow | FactRow | KnowledgeRow


@dataclass(frozen=True)
class _Loaded:
    ref: CommitRef
    manuscript: Manuscript
    base: RevisionRef
    proposals: dict[SlotId, Proposal]


class _LostRaceError(Exception):
    """커밋 트랜잭션 안에서 머리가 기준과 다르다는 것을 알았다 — 트랜잭션째 되돌린다."""


async def _head(session: AsyncSession, novel_id: uuid.UUID) -> RevisionRef:
    row = (
        await session.execute(
            select(NovelBibleRevision.id, NovelBibleRevision.revision_no)
            .where(NovelBibleRevision.novel_id == novel_id, NovelBibleRevision.branch == CANON)
            .order_by(NovelBibleRevision.revision_no.desc())
            .limit(1)
        )
    ).one_or_none()
    return RevisionRef(id=None, revision_no=0) if row is None else RevisionRef(id=row.id, revision_no=row.revision_no)


def _unfinished_jobs() -> Exists:
    return exists().where(
        NovelBibleJob.commit_id == NovelBibleCommit.id, NovelBibleJob.status.in_(("queued", "running"))
    )


async def start_linking(session: AsyncSession, commit_id: uuid.UUID) -> CommitStatus | None:
    """작업이 모두 끝난 추출 확정을 연결로(지금 머리를 기준으로) 또는 실패로 넘긴다. 이 전이는 하나만 이긴다 — 진 쪽은 None."""
    novel_id = await session.scalar(select(NovelBibleCommit.novel_id).where(NovelBibleCommit.id == commit_id))
    if novel_id is None:
        return None
    head = await _head(session, novel_id)
    unfinished = _unfinished_jobs()
    failed = exists().where(NovelBibleJob.commit_id == NovelBibleCommit.id, NovelBibleJob.status == "failed")
    ready = (NovelBibleCommit.id == commit_id, NovelBibleCommit.status == "extracting", ~unfinished)
    linking = await session.scalar(
        update(NovelBibleCommit)
        .where(*ready, ~failed)
        .values(status="linking", base_revision_id=head.id, stage_started_at=func.now())
        .returning(NovelBibleCommit.id)
    )
    if linking is not None:
        return "linking"
    gave_up = await session.scalar(
        update(NovelBibleCommit)
        .where(*ready, failed)
        .values(status="failed", failure_code="slot_failed", finished_at=func.now())
        .returning(NovelBibleCommit.id)
    )
    return "failed" if gave_up is not None else None


async def _transition(
    factory: SessionFactory, commit_id: uuid.UUID, current: CommitStatus, after: CommitStatus
) -> bool:
    async with factory() as session, session.begin():
        moved = await session.scalar(
            update(NovelBibleCommit)
            .where(NovelBibleCommit.id == commit_id, NovelBibleCommit.status == current)
            .values(status=after)
            .returning(NovelBibleCommit.id)
        )
    return moved is not None


async def _fail(factory: SessionFactory, commit_id: uuid.UUID, code: CommitFailure) -> None:
    async with factory() as session, session.begin():
        await session.execute(
            update(NovelBibleCommit)
            .where(NovelBibleCommit.id == commit_id, NovelBibleCommit.status.in_(IN_FLIGHT))
            .values(status="failed", failure_code=code, finished_at=func.now())
        )


async def _load(factory: SessionFactory, registry: Registry, commit_id: uuid.UUID) -> _Loaded | None:
    async with factory() as session:
        commit = await session.get(NovelBibleCommit, commit_id)
        if commit is None or commit.status != "linking":
            return None
        ref = await commit_ref(session, commit)
        revision = await session.get(NovelChapterRevision, ref.chapter_revision_id)
        assert revision is not None  # 개정이 지워지면 확정 행도 CASCADE 로 사라진다
        base_no = await session.scalar(
            select(NovelBibleRevision.revision_no).where(NovelBibleRevision.id == commit.base_revision_id)
        )
        proposals = {
            slot: Proposal.model_validate(proposal)
            for slot, proposal in (
                await session.execute(
                    select(NovelBibleJob.slot, NovelBibleJob.proposal).where(
                        NovelBibleJob.commit_id == commit_id, NovelBibleJob.status == "succeeded"
                    )
                )
            ).tuples()
            if slot in registry.extracting and proposal is not None
        }
        # 기준 리비전이 그 사이 지워졌으면 번호 0 으로 읽는다 — 그 확정은 커밋 때 머리 비교에서 지고 새 기준으로 다시 돈다.
        return _Loaded(ref, manuscript_of(revision), RevisionRef(commit.base_revision_id, base_no or 0), proposals)


async def _entity_ids(
    factory: SessionFactory, loaded: _Loaded
) -> dict[tuple[EntityKind, str], uuid.UUID] | None:
    """이름마다 개체 id — 없으면 만든다. 짧은 별도 트랜잭션이고, 화 행 → 확정 행 순으로 잡은 뒤 확정이 아직 연결 중일 때만
    쓴다. 그래서 숨긴 소설 정리·삭제가 확정을 지운 뒤에는 개체가 새로 생기지 않고, 이쪽이 먼저면 정리가 기다렸다가 함께
    지운다."""
    wanted: dict[tuple[EntityKind, str], str] = {}
    for proposal in loaded.proposals.values():
        for draft in proposal.items:
            for names in draft.names.values():
                for name in names:
                    norm = normalize_name(name.name)
                    if norm:
                        wanted.setdefault((name.kind, norm), name.name.strip())
    async with factory() as session, session.begin():
        chapter = await session.scalar(
            select(NovelChapter.id)
            .where(NovelChapter.id == loaded.ref.chapter_id)
            .with_for_update(read=True, key_share=True)
        )
        status = await session.scalar(
            select(NovelBibleCommit.status)
            .where(NovelBibleCommit.id == loaded.ref.commit_id)
            .with_for_update(read=True)
        )
        if chapter is None or status != "linking":
            return None
        if wanted:
            # 유니크 열쇠 (종류, 정규 이름) 차례로 넣는다. 같은 소설의 연결 둘이 겹치는 이름을 서로 다른 차례로 넣으면 각자 앞
            # 이름의 아직 커밋되지 않은 행을 기다려 교착한다 — 차례가 같으면 뒤 쪽이 앞 쪽을 기다리기만 한다.
            await session.execute(
                insert(NovelBibleEntity)
                .values(
                    [
                        {"novel_id": loaded.ref.novel_id, "kind": kind, "name": name, "name_norm": norm}
                        for (kind, norm), name in sorted(wanted.items())
                    ]
                )
                .on_conflict_do_nothing(index_elements=["novel_id", "kind", "name_norm"])
            )
        rows = (
            await session.execute(
                select(NovelBibleEntity.id, NovelBibleEntity.kind, NovelBibleEntity.name_norm).where(
                    NovelBibleEntity.novel_id == loaded.ref.novel_id,
                    NovelBibleEntity.name_norm.in_({norm for _, norm in wanted}),
                )
            )
        ).all()
    return {(row.kind, row.name_norm): row.id for row in rows}


def _identity(table: ItemTable, key: uuid.UUID | None, knower: uuid.UUID | None, kind: object) -> tuple[object, ...]:
    return (table, key) if table == "fact" else (table, key, knower, kind)


def _link(
    loaded: _Loaded, entities: dict[tuple[EntityKind, str], uuid.UUID], base_rows: Sequence[Row]
) -> dict[SlotId, list[LinkedItem]]:
    """제안을 연결한다 — 이름 → 개체 id, 사실·지식의 앵커 블록 → 이번 확정의 사건, 명제 → 안정 키(주어·대상 개체 id 를 푼
    뒤에), 같은 화 이전 확정의 같은 명제 행 → 대체 대상. 코어가 푸는 이름(앎 주체·명제의 주어·대상)이 비는 항목은 작업을 저장하기
    전에 버렸으므로 여기서는 늘 개체가 있다."""
    block_order = {block.block_id: block.index for block in loaded.manuscript.blocks}
    ids = {(slot, draft.local_key): uuid.uuid4() for slot, p in loaded.proposals.items() for draft in p.items}
    events = sorted(
        (
            (min(block_order.get(block, len(block_order) + 1) for block in draft.covers_blocks), number, ids[slot, draft.local_key], draft)
            for slot, proposal in loaded.proposals.items()
            for number, draft in enumerate(proposal.items)
            if draft.table == "event" and draft.covers_blocks
        ),
        key=lambda event: (event[0], event[1]),
    )

    def anchored(block: uuid.UUID | None) -> uuid.UUID | None:
        if block is None or block not in block_order:
            return None
        for _, _, event_id, draft in events:
            if block in draft.covers_blocks:
                return event_id
        best: tuple[int, uuid.UUID] | None = None
        for _, _, event_id, draft in events:
            before = [block_order[b] for b in draft.covers_blocks if block_order.get(b, 0) < block_order[block]]
            if before and (best is None or max(before) > best[0]):
                best = (max(before), event_id)
        return best[1] if best else None

    previous: dict[tuple[object, ...], list[uuid.UUID]] = {}
    for row in base_rows:
        if row.chapter_id != loaded.ref.chapter_id:
            continue
        if isinstance(row, FactRow):
            previous.setdefault(_identity("fact", row.fact_key, None, None), []).append(row.id)
        elif isinstance(row, KnowledgeRow):
            previous.setdefault(_identity("knowledge", row.fact_key, row.knower_entity_id, row.kind), []).append(row.id)

    linked: dict[SlotId, list[LinkedItem]] = {}
    for slot, proposal in loaded.proposals.items():
        for draft in proposal.items:
            entity_ids = {
                field: tuple(entities[name.kind, normalize_name(name.name)] for name in names
                             if (name.kind, normalize_name(name.name)) in entities)
                for field, names in draft.names.items()
            }
            key = None
            if draft.proposition is not None:
                value = entity_ids.get("value", ())
                key = proposition_key(draft.proposition, entity_ids["subject"][0], value[0] if value else None)
            supersedes = None
            if draft.table in ("fact", "knowledge"):
                knower = entity_ids["knower"][0] if draft.table == "knowledge" else None
                candidates = previous.get(_identity(draft.table, key, knower, draft.fields.get("kind")), [])
                # 같은 키가 여럿이면 화 안 차례대로 짝짓는다.
                supersedes = candidates.pop(0) if candidates else None
            linked.setdefault(slot, []).append(
                LinkedItem(
                    id=ids[slot, draft.local_key],
                    draft=draft,
                    entity_ids=entity_ids,
                    event_id=anchored(draft.anchor_block),
                    fact_key=key,
                    supersedes_id=supersedes,
                )
            )
    return linked


async def _base_rows(factory: SessionFactory, registry: Registry, loaded: _Loaded) -> list[Row]:
    rows: list[Row] = []
    async with factory() as session:
        for slot in registry.extracting.values():
            rows += await slot.read(session, loaded.ref.novel_id, loaded.base)
    return rows


async def _check(
    factory: SessionFactory, registry: Registry, rules: Sequence[Rule], loaded: _Loaded,
    linked: dict[SlotId, list[LinkedItem]], base_rows: Sequence[Row],
) -> list[FindingDraft]:
    """기준 시점 정본에서 이번 화의 현재 항목을 빼고 이번 확정의 새 항목을 더한 스냅숏으로 규칙을 돌린다. 이번 확정의 새 항목이
    하나도 끼지 않은 결과는 버린다. 차단 결과는 관련 항목 모두의 원고 근거가 지금도 맞을 때만 차단이고, 하나라도 맞지 않으면
    경고(`evidence_unverified`)로 낮춘다."""
    new_rows: list[Row] = []
    for slot_id, items in linked.items():
        new_rows += registry.extracting[slot_id].rows(items, loaded.ref)
    new_ids = frozenset(item.id for items in linked.values() for item in items)
    kept = [row for row in base_rows if row.chapter_id != loaded.ref.chapter_id]
    snapshot = assemble(registry, [*kept, *new_rows], new_ids)
    findings = [
        finding
        for rule in rules
        if rule.slots <= registry.ids()
        for finding in rule.check(snapshot)
        if new_ids & set(finding.item_ids)
    ]
    blocking = {item for finding in findings if finding.severity == "block" for item in finding.item_ids}
    if not blocking:
        return findings
    quotes = {item.id: item.draft.quotes for items in linked.values() for item in items}
    async with factory() as session:
        verified = await manuscript_evidence_verified(session, blocking, quotes, loaded.ref.chapter_revision_id)
    return [
        FindingDraft(
            severity="warning", rule="evidence_unverified", item_ids=finding.item_ids,
            payload={**finding.payload, "rule": finding.rule},
        )
        if finding.severity == "block" and not all(verified[item] for item in finding.item_ids)
        else finding
        for finding in findings
    ]


def _finding_rows(loaded: _Loaded, findings: Sequence[FindingDraft]) -> list[NovelBibleFinding]:
    return [
        NovelBibleFinding(
            novel_id=loaded.ref.novel_id,
            commit_id=loaded.ref.commit_id,
            severity=finding.severity,
            rule=finding.rule,
            payload={**finding.payload, "items": [str(item) for item in finding.item_ids]},
        )
        for finding in findings
    ]


async def _block(factory: SessionFactory, loaded: _Loaded, findings: Sequence[FindingDraft]) -> None:
    async with factory() as session, session.begin():
        blocked = await session.scalar(
            update(NovelBibleCommit)
            .where(NovelBibleCommit.id == loaded.ref.commit_id, NovelBibleCommit.status == "checking")
            .values(status="blocked", finished_at=func.now())
            .returning(NovelBibleCommit.id)
        )
        if blocked is not None:
            session.add_all(_finding_rows(loaded, findings))


def _evidence_rows(loaded: _Loaded, revision_id: uuid.UUID, item: LinkedItem) -> list[NovelBibleEvidence]:
    draft: ItemDraft = item.draft
    common = {
        "novel_id": loaded.ref.novel_id, "created_revision_id": revision_id, "item_table": draft.table,
        "item_id": item.id,
    }
    rows = [
        NovelBibleEvidence(
            origin="manuscript_block", chapter_id=loaded.ref.chapter_id,
            chapter_revision_id=loaded.ref.chapter_revision_id, block_id=quote.block_id,
            char_start=quote.char_start, char_end=quote.char_end, quote_sha256=quote.quote_sha256, **common,
        )
        for quote in draft.quotes
    ]
    for side in draft.side_quotes:
        if side.origin == "source_canon":
            rows.append(
                NovelBibleEvidence(
                    origin="source_canon", content_version_id=side.content_version_id,
                    source_field=side.source_field, keyword_note_id=side.keyword_note_id,
                    char_start=side.char_start, char_end=side.char_end, quote_sha256=side.quote_sha256, **common,
                )
            )
        else:
            rows.append(
                NovelBibleEvidence(
                    origin="chat_memory", chat_room_id=side.chat_room_id,
                    chat_memory_fact_id=side.chat_memory_fact_id, chat_fact_key=side.chat_fact_key, **common,
                )
            )
    return rows


async def _current_candidates(session: AsyncSession, loaded: _Loaded, at: RevisionRef) -> list[uuid.UUID]:
    created = aliased(NovelBibleRevision)
    expiring = aliased(NovelBibleRevision)
    expired = (
        select(NovelBibleExpiration.item_id)
        .join(expiring, expiring.id == NovelBibleExpiration.revision_id)
        .where(
            NovelBibleExpiration.item_table == "adaptation_candidate",
            NovelBibleExpiration.item_id == NovelBibleAdaptationCandidate.id,
            expiring.revision_no <= at.revision_no,
        )
        .exists()
    )
    return list(
        await session.scalars(
            select(NovelBibleAdaptationCandidate.id)
            .join(created, created.id == NovelBibleAdaptationCandidate.created_revision_id)
            .where(
                NovelBibleAdaptationCandidate.chapter_id == loaded.ref.chapter_id,
                created.revision_no <= at.revision_no,
                ~expired,
            )
        )
    )


async def _commit(
    factory: SessionFactory, registry: Registry, loaded: _Loaded, linked: dict[SlotId, list[LinkedItem]],
    warnings: Sequence[FindingDraft],
) -> str:
    """돌려주는 값은 `committed`·`lost`(머리 비교에서 짐 — 같은 머리 위 동시 커밋의 번호 유니크 위반, 지워지는 머리를 앞
    리비전으로 가리킨 FK 위반도)·`chapter_gone`·`gone`(확정이 더는 검사 중이 아니다) 중 하나."""
    ref = loaded.ref
    async with factory() as session:
        try:
            async with session.begin():
                chapter = await session.scalar(
                    select(NovelChapter.id)
                    .where(NovelChapter.id == ref.chapter_id)
                    .with_for_update(read=True, key_share=True)
                )
                if chapter is None:
                    return "chapter_gone"
                current = (
                    await session.execute(
                        select(NovelBibleCommit.status, NovelBibleCommit.base_revision_id)
                        .where(NovelBibleCommit.id == ref.commit_id)
                        .with_for_update()
                    )
                ).one_or_none()
                if current is None or current.status != "checking":
                    return "gone"
                head = await _head(session, ref.novel_id)
                if head.id != current.base_revision_id:
                    raise _LostRaceError
                revision = NovelBibleRevision(
                    id=uuid.uuid4(), novel_id=ref.novel_id, branch=CANON, revision_no=head.revision_no + 1,
                    parent_revision_id=head.id, commit_id=ref.commit_id,
                )
                session.add(revision)
                await session.flush()
                expiring: list[tuple[ItemTable, uuid.UUID]] = []
                for slot in registry.extracting.values():
                    expiring += await slot.current_item_ids(session, ref.novel_id, ref.chapter_id, head)
                expiring += [("adaptation_candidate", item) for item in await _current_candidates(session, loaded, head)]
                session.add_all(
                    [
                        NovelBibleExpiration(
                            revision_id=revision.id, novel_id=ref.novel_id, item_table=table, item_id=item_id,
                            reason="chapter_replaced",
                        )
                        for table, item_id in expiring
                    ]
                )
                await session.flush()
                at = RevisionRef(id=revision.id, revision_no=revision.revision_no)
                # 사실·지식 행이 사건 행을 FK 로 가리키므로 사건 슬롯을 먼저 쓴다.
                for slot_id in sorted(linked, key=lambda slot_id: slot_id != "events"):
                    await registry.extracting[slot_id].apply(session, linked[slot_id], ref, at)
                for items in linked.values():
                    for item in items:
                        session.add_all(_evidence_rows(loaded, revision.id, item))
                        origins = {side.origin for side in item.draft.side_quotes}
                        if item.draft.table == "fact" and item.fact_key is not None:
                            session.add_all(
                                [
                                    NovelBibleAdaptationCandidate(
                                        novel_id=ref.novel_id, created_revision_id=revision.id,
                                        chapter_id=ref.chapter_id, fact_key=item.fact_key, fact_id=item.id,
                                        origin=origin,
                                    )
                                    for origin in sorted(origins)
                                ]
                            )
                session.add_all(_finding_rows(loaded, warnings))
                await session.flush()
                await session.execute(
                    update(NovelBibleCommit)
                    .where(NovelBibleCommit.id == ref.commit_id, NovelBibleCommit.status == "checking")
                    .values(status="committed", finished_at=func.now())
                )
            return "committed"
        except _LostRaceError:
            return "lost"
        except IntegrityError as error:
            if _REVISION_NUMBER_INDEX in str(error.orig) or _PARENT_REVISION_FK in str(error.orig):
                return "lost"
            raise


async def _relink(factory: SessionFactory, commit_id: uuid.UUID) -> bool:
    """머리 비교에서 진 확정을 새 머리를 기준으로 다시 연결로 돌린다. 이미 `CAS_LIMIT` 번째로 졌으면 실패로 끝낸다."""
    async with factory() as session, session.begin():
        novel_id = await session.scalar(select(NovelBibleCommit.novel_id).where(NovelBibleCommit.id == commit_id))
        if novel_id is None:
            return False
        checking = (NovelBibleCommit.id == commit_id, NovelBibleCommit.status == "checking")
        exhausted = await session.scalar(
            update(NovelBibleCommit)
            .where(*checking, NovelBibleCommit.cas_losses >= CAS_LIMIT - 1)
            .values(status="failed", failure_code="cas_exhausted", cas_losses=NovelBibleCommit.cas_losses + 1,
                    finished_at=func.now())
            .returning(NovelBibleCommit.id)
        )
        if exhausted is not None:
            return False
        head = await _head(session, novel_id)
        again = await session.scalar(
            update(NovelBibleCommit)
            .where(*checking)
            .values(status="linking", base_revision_id=head.id, cas_losses=NovelBibleCommit.cas_losses + 1,
                    stage_started_at=func.now())
            .returning(NovelBibleCommit.id)
        )
    return again is not None


async def link_check_commit(
    factory: SessionFactory, registry: Registry, rules: Sequence[Rule], commit_id: uuid.UUID
) -> None:
    """연결 중인 확정 하나를 끝 상태까지(또는 다른 쪽이 밀어내 멈출 때까지) 돌린다. 예상하지 못한 예외는 `failed(internal)` —
    커밋 트랜잭션째 되돌아가 리비전·항목·만료가 하나도 남지 않는다."""
    try:
        while True:
            loaded = await _load(factory, registry, commit_id)
            if loaded is None:
                return
            entities = await _entity_ids(factory, loaded)
            if entities is None:
                return
            base_rows = await _base_rows(factory, registry, loaded)
            linked = _link(loaded, entities, base_rows)
            if not await _transition(factory, commit_id, "linking", "checking"):
                return
            findings = await _check(factory, registry, rules, loaded, linked, base_rows)
            if any(finding.severity == "block" for finding in findings):
                await _block(factory, loaded, findings)
                return
            outcome = await _commit(factory, registry, loaded, linked, findings)
            if outcome == "chapter_gone":
                await _fail(factory, commit_id, "chapter_gone")
            if outcome != "lost" or not await _relink(factory, commit_id):
                return
    except Exception:
        logger.exception("정본 기억 확정 %s 처리 실패", commit_id)
        await _fail(factory, commit_id, "internal")


async def process_ready_commit(
    factory: SessionFactory, registry: Registry, rules: Sequence[Rule], *, novel_id: uuid.UUID | None = None
) -> bool:
    """작업이 모두 끝난 추출 확정 하나를 골라 끝까지 처리한다. 고를 것이 없으면 거짓."""
    async with factory() as session, session.begin():
        candidate = (
            select(NovelBibleCommit.id)
            .where(NovelBibleCommit.status == "extracting", ~_unfinished_jobs())
            .order_by(NovelBibleCommit.created_at)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        if novel_id is not None:
            candidate = candidate.where(NovelBibleCommit.novel_id == novel_id)
        commit_id = await session.scalar(candidate)
        if commit_id is None:
            return False
        status = await start_linking(session, commit_id)
    if status == "linking":
        await link_check_commit(factory, registry, rules, commit_id)
    return True


async def run_until_idle(
    factory: SessionFactory, registry: Registry, rules: Sequence[Rule], resolver: AdapterResolver, *,
    novel_id: uuid.UUID | None = None, max_steps: int = 1_000,
) -> int:
    """준비된 확정 처리 → 대기 작업 실행을 할 일이 없을 때까지(또는 `max_steps` 번) 한다. 돌린 단계 수를 돌려준다. 재시도
    대기 중인 작업은 대기 시각 전에는 고르지 않는다."""
    steps = 0
    while steps < max_steps:
        if not (
            await process_ready_commit(factory, registry, rules, novel_id=novel_id)
            or await run_next_job(factory, registry, resolver, novel_id=novel_id)
        ):
            break
        steps += 1
    return steps
