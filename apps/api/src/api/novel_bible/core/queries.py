"""시간 세 축의 질의 넷.

- 편집 확정 시간 = 정본 기억 리비전. 리비전 r 시점의 정본(`bible_at`)은 r 이하 리비전이 넣고 r 이하 리비전이 만료하지 않은
  항목이다. 슬롯은 `current_items` 로 자기 표를 이 꼴로 읽는다.
- 이야기 시간 = 사건과 부분 순서(`positions`). 사건 시점에 참인 사실(`facts_true_at`)과 인물이 아는 것(`knowledge_at`).
- 독자 공개 시간 = 저장하지 않는다. 공개본·판 행이 보여 준 블록의 글에서 파생한다(`revealed_facts`)."""

import hashlib
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import Select, bindparam, select, text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased
from sqlalchemy.types import Integer, Uuid

from api.db.models.novel_bible import NovelBibleExpiration, NovelBibleRevision
from api.novel_bible.core.contracts import Registry
from api.novel_bible.core.positions import Interval, precedes, story_positions
from api.novel_bible.core.types import BibleSnapshot, EventRow, FactRow, KnowledgeRow, RelationRow, RevisionRef
from api.novel_bible.ids import ItemTable
from api.novelize.text import split_paragraphs

CANON = "canon"


def current_items(model: Any, item_table: ItemTable, novel_id: uuid.UUID, at: RevisionRef) -> Select[Any]:
    """항목 표 `model` 에서 리비전 `at` 시점에 현재인 확정 항목을 고르는 문장."""
    created = aliased(NovelBibleRevision)
    expiring = aliased(NovelBibleRevision)
    expired = (
        select(NovelBibleExpiration.item_id)
        .join(expiring, expiring.id == NovelBibleExpiration.revision_id)
        .where(
            NovelBibleExpiration.item_table == item_table,
            NovelBibleExpiration.item_id == model.id,
            expiring.branch == CANON,
            expiring.revision_no <= at.revision_no,
        )
        .exists()
    )
    return (
        select(model)
        .join(created, created.id == model.created_revision_id)
        .where(
            model.novel_id == novel_id,
            model.status == "confirmed",
            created.branch == CANON,
            created.revision_no <= at.revision_no,
            ~expired,
        )
    )


async def revision_at(session: AsyncSession, novel_id: uuid.UUID, revision_no: int | None) -> RevisionRef:
    """번호 `revision_no` 의 리비전(없으면 머리). 리비전이 하나도 없으면 번호 0."""
    statement = select(NovelBibleRevision.id, NovelBibleRevision.revision_no).where(
        NovelBibleRevision.novel_id == novel_id, NovelBibleRevision.branch == CANON
    )
    if revision_no is not None:
        statement = statement.where(NovelBibleRevision.revision_no <= revision_no)
    row = (await session.execute(statement.order_by(NovelBibleRevision.revision_no.desc()).limit(1))).one_or_none()
    if row is None:
        return RevisionRef(id=None, revision_no=0)
    return RevisionRef(id=row.id, revision_no=row.revision_no if revision_no is None else revision_no)


async def snapshot_at(
    session: AsyncSession, novel_id: uuid.UUID, registry: Registry, at: RevisionRef
) -> BibleSnapshot:
    rows: list[EventRow | RelationRow | FactRow | KnowledgeRow] = []
    for slot in registry.extracting.values():
        rows += await slot.read(session, novel_id, at)
    return assemble(registry, rows)


def assemble(
    registry: Registry,
    rows: list[EventRow | RelationRow | FactRow | KnowledgeRow],
    new_ids: frozenset[uuid.UUID] = frozenset(),
) -> BibleSnapshot:
    """행들을 슬롯별 칸으로 나눈다. 등록되지 않은 슬롯의 칸은 None 이다 — 코어가 슬롯 id 를 아는 곳은 이 자리뿐이다."""
    ids = registry.extracting.keys()
    return BibleSnapshot(
        events=tuple(r for r in rows if isinstance(r, EventRow)) if "events" in ids else None,
        relations=tuple(r for r in rows if isinstance(r, RelationRow)) if "events" in ids else None,
        facts=tuple(r for r in rows if isinstance(r, FactRow)) if "facts" in ids else None,
        knowledge=tuple(r for r in rows if isinstance(r, KnowledgeRow)) if "knowledge" in ids else None,
        new_ids=new_ids,
    )


async def bible_at(
    session: AsyncSession, novel_id: uuid.UUID, registry: Registry, *, revision_no: int | None
) -> BibleSnapshot:
    """리비전 `revision_no`(None 이면 머리) 시점에 현재인 항목. 등록되지 않은 슬롯은 None 이다."""
    return await snapshot_at(session, novel_id, registry, await revision_at(session, novel_id, revision_no))


@dataclass(frozen=True)
class FactsAtEvent:
    """상태 키마다 그 사건 시점의 행(`holds` 가 거짓이면 "아님"). 순서가 미정인 행은 참으로 세지 않고 `undetermined` 로
    따로 낸다 — 그런 행이 가장 늦은 행일 수 있는 키는 `states` 에 없다."""

    states: Mapping[uuid.UUID, FactRow]
    undetermined: tuple[FactRow, ...]


@dataclass(frozen=True)
class KnowledgeAtEvent:
    """`knows` 는 그 사건 시점에 참인 같은 키의 사실과 짝지어(없으면 None — 사실 미정), `believes` 는 명제 그대로 따로 낸다."""

    knows: tuple[tuple[KnowledgeRow, FactRow | None], ...]
    believes: tuple[KnowledgeRow, ...]
    undetermined: tuple[KnowledgeRow, ...] = field(default=())


def _start(
    fact: FactRow, positions: Mapping[uuid.UUID, Interval | None], actual: set[uuid.UUID]
) -> Interval | str | None:
    """사실이 시작한 자리 — 작품 범위면 "work", 시작 사건이 꿈·상상이면 "dream", 그 밖은 시작 사건의 위치(미정이면 None)."""
    if fact.scope == "work":
        return "work"
    if fact.valid_from_event_id is None:
        return None
    if fact.valid_from_event_id not in actual:
        return "dream" if fact.valid_from_event_id in positions else None
    return positions[fact.valid_from_event_id]


def _facts_at(snapshot: BibleSnapshot, event_id: uuid.UUID) -> FactsAtEvent:
    if snapshot.facts is None:
        return FactsAtEvent(states={}, undetermined=())
    events = snapshot.events or ()
    positions = story_positions(events, snapshot.relations or ())
    actual = {event.id for event in events if event.actuality in ("present", "flashback")}
    here = positions.get(event_id)
    candidates: dict[uuid.UUID, list[tuple[FactRow, Interval | str | None]]] = {}
    unknown: dict[uuid.UUID, list[tuple[FactRow, Interval | None]]] = {}
    for fact in snapshot.facts:
        start = _start(fact, positions, actual)
        if start == "dream":
            continue
        if start == "work":
            candidates.setdefault(fact.fact_key, []).append((fact, "work"))
            continue
        assert not isinstance(start, str)
        if fact.valid_from_event_id == event_id:
            relation: bool | None = True
        elif fact.scope == "scene":
            relation = False
        else:
            relation = precedes(start, here)
        if relation is True:
            candidates.setdefault(fact.fact_key, []).append((fact, start))
        elif relation is None:
            unknown.setdefault(fact.fact_key, []).append((fact, start))

    def follows(first: Interval | str | None, second: Interval | str | None) -> bool:
        if first == "work":
            return second != "work"
        if isinstance(first, str) or isinstance(second, str):
            return False
        return precedes(first, second) is True

    states: dict[uuid.UUID, FactRow] = {}
    undetermined = [fact for rows in unknown.values() for fact, _ in rows]
    for key, rows in candidates.items():
        latest = [(f, s) for f, s in rows if not any(follows(s, other) for g, other in rows if g is not f)]
        blocking = [
            fact for fact, start in unknown.get(key, []) if not any(follows(start, other) for _, other in rows)
        ]
        if len({(fact.value_norm, fact.holds) for fact, _ in latest}) == 1 and not blocking:
            states[key] = latest[0][0]
        else:
            undetermined += [fact for fact, _ in latest if fact not in undetermined]
    return FactsAtEvent(states=states, undetermined=tuple(undetermined))


async def facts_true_at(
    session: AsyncSession, novel_id: uuid.UUID, registry: Registry, *, event_id: uuid.UUID,
    revision_no: int | None = None,
) -> FactsAtEvent:
    """상태 키마다 사건 `event_id` 이전(이야기 순서)에 시작한 행 중 가장 늦은 것. 작품 범위 행은 늘 후보이고(가장 이르다),
    장면 범위 행은 시작 사건이 그 사건일 때만, 꿈·상상 사건에서 시작한 행은 상태가 아니다. 가장 늦은 후보가 여럿이고 값이
    다르면 그 키는 미정이다."""
    return _facts_at(await bible_at(session, novel_id, registry, revision_no=revision_no), event_id)


async def knowledge_at(
    session: AsyncSession, novel_id: uuid.UUID, registry: Registry, *, knower_entity_id: uuid.UUID,
    event_id: uuid.UUID, revision_no: int | None = None,
) -> KnowledgeAtEvent:
    """앎 주체가 `knower_entity_id` 이고 알게 된 사건이 `event_id` 이전이거나 같은 지식. 알게 된 사건이 미정이거나 순서를
    모르면 `undetermined`."""
    snapshot = await bible_at(session, novel_id, registry, revision_no=revision_no)
    if snapshot.knowledge is None:
        return KnowledgeAtEvent(knows=(), believes=())
    positions = story_positions(snapshot.events or (), snapshot.relations or ())
    here = positions.get(event_id)
    facts = _facts_at(snapshot, event_id).states
    knows: list[tuple[KnowledgeRow, FactRow | None]] = []
    believes: list[KnowledgeRow] = []
    undetermined: list[KnowledgeRow] = []
    for row in snapshot.knowledge:
        if row.knower_entity_id != knower_entity_id:
            continue
        if row.known_since_event_id == event_id:
            relation: bool | None = True
        elif row.known_since_event_id is None:
            relation = None
        else:
            relation = precedes(positions.get(row.known_since_event_id), here)
        if relation is None:
            undetermined.append(row)
        elif relation:
            if row.kind == "knows":
                knows.append((row, facts.get(row.fact_key)))
            else:
                believes.append(row)
    return KnowledgeAtEvent(knows=tuple(knows), believes=tuple(believes), undetermined=tuple(undetermined))


# 심사 대기·반려는 공개 범위가 거둠이라(공개 상태 CHECK) 심사 칸만 보면 된다. 승인 뒤 작가가 거둔 소설은 드러난 것으로 센다 —
# 한 번 독자에게 나갔고 산 사람은 계속 읽는다.
_REVEALED_EVIDENCE = text(
    """
WITH approved AS (
  SELECT 1 FROM novel_publications p
   WHERE p.novel_id = :novel_id AND (p.review_status IS NULL OR p.review_status = 'approved')
), shown(chapter_id, revision_id) AS (
  SELECT cp.chapter_id, cp.revision_id FROM novel_chapter_publications cp
   WHERE cp.novel_id = :novel_id AND EXISTS (SELECT 1 FROM approved)
     AND cp.chapter_id <> ALL(:pinned_chapter_ids)
  UNION ALL
  SELECT e.chapter_id, e.revision_id
    FROM novel_chapter_editions e
    JOIN unnest(:pinned_chapter_ids, :pinned_editions) AS pin(chapter_id, edition)
      ON pin.chapter_id = e.chapter_id AND pin.edition = e.edition
   WHERE e.novel_id = :novel_id AND EXISTS (SELECT 1 FROM approved)
)
SELECT ev.item_id, ev.block_id, ev.char_start, ev.char_end, ev.quote_sha256, r.body, r.block_ids
  FROM novel_bible_evidence ev
  JOIN shown s ON s.chapter_id = ev.chapter_id
  JOIN novel_chapter_revisions r ON r.id = s.revision_id
 WHERE ev.novel_id = :novel_id AND ev.item_table = 'fact' AND ev.origin = 'manuscript_block'
   AND ev.block_id = ANY(r.block_ids)
"""
).bindparams(
    bindparam("pinned_chapter_ids", type_=ARRAY(Uuid)),
    bindparam("pinned_editions", type_=ARRAY(Integer)),
)


async def revealed_facts(
    session: AsyncSession, novel_id: uuid.UUID, registry: Registry, *, revision_no: int | None = None,
    editions: Mapping[uuid.UUID, int] | None = None,
) -> list[FactRow]:
    """독자에게 드러난 사실(리비전 `revision_no` 시점의 정본 안에서). 화마다 현재 공개본, `editions` 에 적은 화는 그 판이 보여
    준 블록 글에서 사실의 원고 근거 구간의 해시가 맞는 근거가 하나라도 있는 사실이다. 판이 지워진 화(반려·신청 취소)는 드러나지
    않은 것이다."""
    snapshot = await bible_at(session, novel_id, registry, revision_no=revision_no)
    if not snapshot.facts:
        return []
    pinned = dict(editions or {})
    rows = (
        await session.execute(
            _REVEALED_EVIDENCE,
            {
                "novel_id": novel_id,
                "pinned_chapter_ids": list(pinned),
                "pinned_editions": list(pinned.values()),
            },
        )
    ).all()
    revealed: set[uuid.UUID] = set()
    for row in rows:
        paragraphs = split_paragraphs(row.body)
        index = list(row.block_ids).index(row.block_id)
        if index < len(paragraphs):
            quoted = paragraphs[index][row.char_start : row.char_end]
            if hashlib.sha256(quoted.encode("utf-8")).hexdigest() == row.quote_sha256:
                revealed.add(row.item_id)
    return [fact for fact in snapshot.facts if fact.id in revealed]
