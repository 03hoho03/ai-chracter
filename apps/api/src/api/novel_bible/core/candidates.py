"""모호 후보 판정의 입력 조립 — 구조 규칙이 후보 표시(`payload["judge"]`)를 실은 경고마다 모델에 보일 후보 글을 만든다.

후보 글은 문안 `candidate` 값이다. 규칙 이름, 항목마다 화 번호·종류(사건·사실·앎·믿음)·코어가 행 칸으로 만든 한 줄 서술·근거
블록에서 위치로 잘라 낸 원고 구절, 그리고 첫 항목과 나머지 항목 사이의 이야기 순서(앞섬·같은 자리·미정)다. 서술은 모델이 낸
요지가 아니라 행 칸(개체 이름·종류·값)으로 만든다 — 판정이 추출 모델의 요약을 다시 읽으면 추출의 잘못을 그대로 믿는다. 구절은
차단 근거 확인과 같은 읽기(`quotes.manuscript_evidence_texts`)로 지금 개정 글과 맞는 것만 싣는다.

항목의 이야기 자리는 그 항목이 놓인 사건의 자리다(사실은 시작 사건, 앎은 알게 된 사건). 작품 범위 사실도 서술된 사건의 자리로
본다 — 판정에 보이는 순서는 원고에서 어디에 적혔는가다."""

import uuid
from collections.abc import Mapping, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.models.novel import NovelChapter
from api.db.models.novel_bible import NovelBibleEntity
from api.novel_bible.core.positions import Interval, precedes, story_positions
from api.novel_bible.core.quotes import manuscript_evidence_texts
from api.novel_bible.core.types import (
    EventRow,
    FactRow,
    FindingDraft,
    JudgeCandidate,
    KnowledgeRow,
    RelationRow,
    VerifiedQuote,
    WarningDraft,
)

Row = EventRow | RelationRow | FactRow | KnowledgeRow
Item = EventRow | FactRow | KnowledgeRow

_ACTUALITY = {"present": "", "flashback": "회상 ", "dream_or_imagined": "꿈·상상 "}
_KIND = {"life": "생사", "presence": "자리", "possession": "소지", "ability": "능력", "attribute": "속성", "relation": "관계"}
_VALUE = {
    ("life", "alive"): "살아 있음",
    ("life", "dead"): "사망",
    ("presence", "present"): "그 자리에 있음",
    ("presence", "departed"): "떠남",
    ("presence", "gone_for_good"): "영구 퇴장",
}


def is_candidate(finding: FindingDraft) -> bool:
    """판정 후보인가 — 후보 표시를 실은 경고."""
    return finding.severity == "warning" and "judge" in finding.payload


def _proposition_line(subject: str, kind: str, attribute: str | None, value: str, holds: bool) -> str:
    label = f"{_KIND.get(kind, kind)} {attribute}" if attribute else _KIND.get(kind, kind)
    ended = "" if holds else " (끝남)"
    return f"{subject} — {label}: {_VALUE.get((kind, value), value)}{ended}"


class _Describer:
    def __init__(self, names: Mapping[uuid.UUID, str]) -> None:
        self._names = names

    def name(self, entity_id: uuid.UUID | None) -> str:
        return self._names.get(entity_id, "이름 없음") if entity_id is not None else "이름 없음"

    def kind(self, item: Item) -> str:
        if isinstance(item, EventRow):
            return "사건"
        if isinstance(item, FactRow):
            return "사실"
        return "앎" if item.kind == "knows" else "믿음"

    def line(self, item: Item) -> str:
        if isinstance(item, EventRow):
            parts = []
            if item.present_entity_ids:
                parts.append("등장: " + ", ".join(self.name(entity) for entity in item.present_entity_ids))
            if item.uses:
                parts.append(
                    "사용: " + ", ".join(f"{self.name(actor)} → {self.name(thing)}" for actor, thing in item.uses)
                )
            head = f"{_ACTUALITY[item.actuality]}사건"
            return f"{head} — {' · '.join(parts)}" if parts else head
        if isinstance(item, FactRow):
            attribute = item.predicate_norm if item.kind in ("attribute", "relation") else None
            return _proposition_line(self.name(item.subject_entity_id), item.kind, attribute, item.value, item.holds)
        about = item.proposition
        verb = "아는 것" if item.kind == "knows" else "믿는 것"
        fact = _proposition_line(
            str(about.get("subject", "")), str(about.get("kind", "")), about.get("attribute"), str(about.get("value", "")),
            bool(about.get("holds", True)),
        )
        return f"{self.name(item.knower_entity_id)} 이(가) {verb}: {fact}"


def _event_of(item: Item) -> uuid.UUID | None:
    if isinstance(item, EventRow):
        return item.id
    if isinstance(item, FactRow):
        return item.valid_from_event_id
    return item.known_since_event_id


def _order(first: Interval | None, other: Interval | None, number: int) -> str:
    if precedes(first, other) is True:
        return "항목 1 이 앞선다"
    if precedes(other, first) is True:
        return f"항목 {number} 가 앞선다"
    if precedes(first, other) is False and precedes(other, first) is False:
        return "같은 자리"
    return "미정"


async def assemble_candidates(
    session: AsyncSession,
    rows: Sequence[Row],
    findings: Sequence[FindingDraft],
    new_quotes: Mapping[uuid.UUID, tuple[VerifiedQuote, ...]],
    new_revision_id: uuid.UUID,
) -> list[JudgeCandidate]:
    """후보 경고마다 판정 입력을 만든다. `rows` 는 검사에 쓴 스냅숏의 행 전부(기준 정본에서 이번 화를 뺀 것 + 이번 확정의 새
    행), `new_quotes` 는 이번 확정 항목의 근거(확정 개정 기준)다."""
    items: dict[uuid.UUID, Item] = {row.id: row for row in rows if not isinstance(row, RelationRow)}
    item_ids = {item_id for finding in findings for item_id in finding.item_ids if item_id in items}
    wanted = {item_id: items[item_id] for item_id in item_ids}
    entity_ids: set[uuid.UUID] = set()
    for item in wanted.values():
        if isinstance(item, EventRow):
            entity_ids.update(item.present_entity_ids)
            entity_ids.update(entity for use in item.uses for entity in use)
        elif isinstance(item, FactRow):
            entity_ids.add(item.subject_entity_id)
        else:
            entity_ids.add(item.knower_entity_id)
    names = dict(
        (await session.execute(select(NovelBibleEntity.id, NovelBibleEntity.name).where(NovelBibleEntity.id.in_(entity_ids))))
        .tuples()
        .all()
    )
    ordinals = dict(
        (
            await session.execute(
                select(NovelChapter.id, NovelChapter.ordinal).where(
                    NovelChapter.id.in_({item.chapter_id for item in wanted.values()})
                )
            )
        )
        .tuples()
        .all()
    )
    quotes = await manuscript_evidence_texts(session, item_ids, new_quotes, new_revision_id)
    events = [row for row in rows if isinstance(row, EventRow)]
    positions = story_positions(events, [row for row in rows if isinstance(row, RelationRow)])
    describe = _Describer(names)

    candidates: list[JudgeCandidate] = []
    for finding in findings:
        members = [wanted[item_id] for item_id in finding.item_ids if item_id in wanted]
        lines = [f"규칙: {finding.rule}"]
        for number, item in enumerate(members, start=1):
            lines.append(f"항목 {number}: {ordinals.get(item.chapter_id, 0)}화 · {describe.kind(item)}")
            lines.append(f"서술: {describe.line(item)}")
            lines += [f"근거: {text}" for text in quotes.get(item.id, [])] or ["근거: 지금 원고에서 다시 찾지 못함"]
        spots = [positions.get(event) if (event := _event_of(item)) is not None else None for item in members]
        if len(members) == 2:
            lines.append(f"순서: {_order(spots[0], spots[1], 2)}")
        else:
            lines += [f"순서(항목 1 · 항목 {number}): {_order(spots[0], spots[number - 1], number)}"
                      for number in range(2, len(members) + 1)]
        candidates.append(
            JudgeCandidate(
                warning=WarningDraft.model_validate(finding.model_dump()),
                chapters=tuple(sorted(ordinals.get(item.chapter_id, 0) for item in members)),
                text="\n".join(lines),
            )
        )
    return candidates
