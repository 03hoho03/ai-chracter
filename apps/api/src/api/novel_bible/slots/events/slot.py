"""사건 슬롯 — 확정 원고에서 사건 노드와 회상 사건의 앞뒤 관계를 뽑아 사건 표·회상 관계 표에 쓴다.

입력은 확정 개정의 문단(장면 경계 표시 포함), 장면 구성안의 장면 제목·회상 표시, 아는 개체, 앞 화의 현재 주선 사건 목록이다.
뒤 둘은 정본 상태에서 오는 힌트라 추출 캐시 열쇠에서 빠진다. 장면 구성안의 다른 내용(요약·목적·근거 구간)은 싣지 않는다 — 계획은
확정된 원고가 아니다. 원문 채팅 구간도 읽지 않는다.

이야기 순서의 기본은 화 번호와 화 안 차례이고, 회상 사건만 앞 화 사건과의 관계(앞·뒤·겹침)를 받는다. 관계 대상은 사건 id 가
아니라 대상 사건의 블록 id 하나로 저장한다 — 대상 화를 다시 확정해도 같은 블록을 덮는 새 사건으로 읽을 때 이어지고, 추출 캐시로
다시 쓰는 제안이 그때의 목록 번호에 기대지 않는다. 읽는 쪽(`core/positions.py`)은 그 블록을 덮는 주선 사건 중 차례가 가장 앞선
것으로 풀기 때문에, 저장하는 블록은 대상 사건의 앵커 가운데 같은 화의 앞 차례 주선 사건이 덮지 않는 첫 블록이다. 그런 블록이 없는
사건(앵커 전부를 앞 사건이 함께 덮는다)을 가리킨 관계는 다른 사건으로 풀리므로 버린다 — 회상의 그 끝은 열린 채(미정)로 남는다.
대상 화를 다시 확정한 뒤 새 사건들이 그 블록을 어떻게 나눠 덮는지까지는 막지 못한다.

현실성은 장면 구성안이 회상이라고 한 장면의 `present` 사건만 `flashback` 으로 올린다. 모델이 회상·꿈이라고 한 것은 그대로 둔다 —
구성안은 꿈을 표시하지 않는다. 구성안이 없는 화(옛 흐름 화)는 화 전체가 장면 하나이고 현실성은 모델 출력으로만 정한다. 꿈·상상
사건이 이야기 순서와 사건 시점의 상태 계산에서 빠지는 것(`core/positions.py`·`core/queries.py`)이 이 칸에 기대므로, 모델이 낸
값을 낮추지 않는다.

다른 슬롯을 모른다 — 사건 표 둘에만 쓰고, 사실·지식이 사건에 이어지는 것은 코어의 연결 단계가 블록으로 푼다."""

import uuid
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.models.novel import NovelChapter
from api.db.models.novel_bible_events import NovelBibleEvent, NovelBibleEventRelation
from api.novel_bible.core.contracts import CoreReadView
from api.novel_bible.core.keys import normalize_name
from api.novel_bible.core.queries import current_items, revision_at
from api.novel_bible.core.quotes import verify_quote
from api.novel_bible.core.types import (
    CommitRef,
    EntityName,
    EventRow,
    ItemDraft,
    LinkedItem,
    Manuscript,
    Proposal,
    RelationRow,
    RevisionRef,
    SceneHint,
    SlotRows,
    VerifiedQuote,
)
from api.novel_bible.ids import EntityKind, EventActuality, ItemTable, OperationKey, SlotId
from api.novel_bible.slots.events.schema import EventsOutput, ExtractedEvent

# 앞 화 사건 목록에 싣는 수 — 이야기 순서로 가장 늦은 것부터 센다.
_PRIOR_LIMIT = 200
# 사건 하나에 남기는 인물 이름 수(등장·언급 각각). 넘는 이름은 자른다.
_NAME_LIMIT = 20
_KIND_LABELS: dict[EntityKind, str] = {"character": "인물", "object": "사물", "ability": "능력"}
_TABLES: tuple[tuple[ItemTable, Any], ...] = (("event", NovelBibleEvent), ("event_relation", NovelBibleEventRelation))


@dataclass(frozen=True)
class PriorEvent:
    """앞 화의 주선 사건 하나. 표지(P1 …)로 프롬프트에 보이고, 회상 관계가 그 표지를 내면 검증이 `target_block_id` 로 푼다.
    `target_block_id` 는 이 사건만 덮는(같은 화의 앞 차례 주선 사건이 덮지 않는) 첫 앵커 블록이고, 없으면 None 이다."""

    label: str
    chapter_id: uuid.UUID
    chapter_ordinal: int
    summary: str
    target_block_id: uuid.UUID | None


class EventsInput(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True)

    manuscript: Manuscript
    scenes: list[SceneHint]
    known: list[EntityName]
    prior: list[PriorEvent]


async def _prior_events(session: AsyncSession, commit: CommitRef) -> list[PriorEvent]:
    """지금 머리 시점에 현재인 사건 중 이 화보다 앞 화의 주선 사건, 이야기 순서대로."""
    head = await revision_at(session, commit.novel_id, None)
    rows = (
        await session.execute(
            current_items(NovelBibleEvent, "event", commit.novel_id, head)
            .add_columns(NovelChapter.ordinal)
            .join(NovelChapter, NovelChapter.id == NovelBibleEvent.chapter_id)
            .where(NovelBibleEvent.actuality == "present", NovelChapter.ordinal < commit.chapter_ordinal)
            .order_by(NovelChapter.ordinal.desc(), NovelBibleEvent.ordinal.desc())
            .limit(_PRIOR_LIMIT)
        )
    ).all()
    # 블록마다 그 블록을 덮는 주선 사건 중 가장 앞 차례. 목록이 상한에서 잘려도 같은 화의 앞 사건을 빠뜨리지 않게, 목록에 든 화의
    # 주선 사건을 상한 없이 다시 읽는다(블록 id 는 화마다 달라 다른 화의 사건은 이 블록을 덮지 않는다).
    first_cover: dict[uuid.UUID, int] = {}
    chapters = list({event.chapter_id for event, _ in rows})
    same_chapter = current_items(NovelBibleEvent, "event", commit.novel_id, head).where(
        NovelBibleEvent.actuality == "present", NovelBibleEvent.chapter_id.in_(chapters)
    )
    for covering in (await session.scalars(same_chapter)).all():
        for block_id in covering.anchor_block_ids:
            first_cover[block_id] = min(first_cover.get(block_id, covering.ordinal), covering.ordinal)
    return [
        PriorEvent(
            label=f"P{number}", chapter_id=event.chapter_id, chapter_ordinal=ordinal, summary=event.summary,
            target_block_id=next(
                (block_id for block_id in event.anchor_block_ids if first_cover[block_id] == event.ordinal), None
            ),
        )
        for number, (event, ordinal) in enumerate(reversed(rows), start=1)
    ]


def _manuscript_text(manuscript: Manuscript, scenes: Sequence[SceneHint]) -> str:
    """문단마다 `[번호] 글`. 장면 구성안이 있으면 장면이 바뀌는 자리에 `[장면 n]` 을 둔다(n 은 장면 힌트의 차례)."""
    number_of = {block_id: number for number, scene in enumerate(scenes, start=1) for block_id in scene.block_ids}
    lines: list[str] = []
    current: int | None = None
    for block in manuscript.blocks:
        number = number_of.get(block.block_id)
        if number is not None and number != current:
            lines.append(f"[장면 {number}]")
            current = number
        lines.append(f"[{block.index}] {block.text}")
    return "\n".join(lines)


def _entity_line(name: EntityName) -> str:
    aliases = f" — 별칭: {', '.join(name.aliases)}" if name.aliases else ""
    return f"- {name.name} ({_KIND_LABELS[name.kind]}){aliases}"


def _characters(names: Iterable[str]) -> tuple[EntityName, ...]:
    kept = [EntityName(kind="character", name=name.strip()) for name in names if normalize_name(name)]
    return tuple(kept[:_NAME_LIMIT])


def _unique(ids: Iterable[uuid.UUID]) -> list[uuid.UUID]:
    return list(dict.fromkeys(ids))


def _event_row(event: NovelBibleEvent, chapter_ordinal: int) -> EventRow:
    return EventRow(
        id=event.id, chapter_id=event.chapter_id, chapter_ordinal=chapter_ordinal, ordinal=event.ordinal,
        actuality=event.actuality, anchor_block_ids=tuple(event.anchor_block_ids),
    )


def _relation_row(relation: NovelBibleEventRelation) -> RelationRow:
    return RelationRow(
        id=relation.id, chapter_id=relation.chapter_id, from_event_id=relation.from_event_id,
        relation=relation.relation, to_anchor_block_id=relation.to_anchor_block_id,
        to_chapter_id=relation.to_chapter_id,
    )


class EventsSlot:
    """사건 슬롯. 검증은 항목 하나씩 버리고 버린 수를 사유별로 센다 — 출력 전체가 스키마에 맞지 않으면 구조화 호출이 실패해 이
    검증까지 오지 않는다."""

    id: SlotId = "events"
    operation: OperationKey = "events.extract"
    channel: str = "novel_bible_events"
    output_schema: type[BaseModel] = EventsOutput
    tables: frozenset[ItemTable] = frozenset({"event", "event_relation"})
    hint_values: frozenset[str] = frozenset({"known_entities", "prior_events"})

    async def build_input(self, session: AsyncSession, view: CoreReadView) -> EventsInput:
        return EventsInput(
            manuscript=await view.manuscript(),
            scenes=await view.scene_hints(),
            known=await view.known_entities(),
            prior=await _prior_events(session, view.commit),
        )

    def prompt_values(self, slot_input: BaseModel) -> dict[str, str]:
        """렌더 값 넷(지시문 섹션 `instruction` 은 값이 없다). 값의 꼴은 이 함수가 정하고, 문안 채널 `novel_bible_events` 의
        지시문이 이 꼴을 모델에게 설명해야 한다 — 꼴을 모르는 지시문은 오류 없이 관계·문단 번호·이름을 틀리게 만든다.

        - `manuscript`: 문단마다 한 줄 `[번호] 글`. 장면 구성안이 있으면 장면이 바뀌는 자리에 `[장면 n]` 줄이 끼는데, 문단
          번호는 이 줄을 세지 않는다. 모델이 내는 `paragraphs`·`quote.paragraph` 는 `[번호]` 의 번호이고, `quote.text` 는
          `[번호] ` 머리 없이 그 문단 글에서 그대로 옮긴 구절이어야 한다 — 인용 검증이 문단 글에서 찾는다.
        - `scene_hints`: 장면마다 한 줄 `장면 n. 제목`, 회상 장면이면 끝에 ` (회상)`. n 은 원고의 `[장면 n]` 과 같다. 구성안이
          없는 화는 빈 값이다(문안이 이 섹션을 조건부로 두면 섹션째 빠진다).
        - `known_entities`: 개체마다 한 줄 `- 이름 (인물)`(종류 자리는 `인물`·`사물`·`능력`), 별칭이 있으면 끝에
          ` — 별칭: a, b`. 같은 줄은 한 번만 싣고 줄은 글자 순으로 정렬한다. 모델이 인물·사물 이름을 낼 때는 이름만 써야 한다 —
          괄호의 종류나 별칭 꼬리를 함께 옮기면 그 글 그대로 다른 개체가 생긴다.
        - `prior_events`: 앞 화 사건마다 한 줄 `P1. 3화 — 요지`. 회상 관계의 `target` 은 표지(`P1`)만 받는다 — 앞뒤 공백 말고
          다른 글자(마침표·괄호·소문자 따위)가 붙으면 그 관계를 버린다."""
        assert isinstance(slot_input, EventsInput)
        return {
            "manuscript": _manuscript_text(slot_input.manuscript, slot_input.scenes),
            "scene_hints": "\n".join(
                f"장면 {number}. {scene.title}" + (" (회상)" if scene.flashback else "")
                for number, scene in enumerate(slot_input.scenes, start=1)
            ),
            "known_entities": "\n".join(sorted({_entity_line(name) for name in slot_input.known})),
            "prior_events": "\n".join(
                f"{prior.label}. {prior.chapter_ordinal}화 — {prior.summary}" for prior in slot_input.prior
            ),
        }

    def validate(self, slot_input: BaseModel, output: BaseModel) -> Proposal:
        """사건: 문단이 비었거나 범위 밖이면, 인용 문단이 사건 문단 밖이면, 인용 구절이 그 문단에 없으면 버린다. 차례는 첫 문단
        순, 장면 키는 첫 문단의 장면이다. 회상 관계: 가리킨 사건이 없거나 회상이 아니면, 표지가 앞 화 목록에 없으면, 표지의 사건만
        덮는 블록이 없으면(다른 사건으로 풀린다) 버린다."""
        assert isinstance(slot_input, EventsInput) and isinstance(output, EventsOutput)
        blocks = slot_input.manuscript.blocks
        scene_of = {block_id: scene for scene in slot_input.scenes for block_id in scene.block_ids}
        dropped: Counter[str] = Counter()
        accepted: list[tuple[list[int], int, ExtractedEvent, VerifiedQuote]] = []
        for position, event in enumerate(output.events):
            paragraphs = sorted(set(event.paragraphs))
            if not paragraphs or not all(1 <= number <= len(blocks) for number in paragraphs):
                dropped["paragraphs_invalid"] += 1
            elif event.quote.paragraph not in paragraphs:
                dropped["quote_outside_event"] += 1
            elif (quote := verify_quote(slot_input.manuscript, event.quote)) is None:
                dropped["quote_not_found"] += 1
            else:
                accepted.append((paragraphs, position, event, quote))
        drafts: list[ItemDraft] = []
        by_key: dict[str, ItemDraft] = {}
        accepted.sort(key=lambda item: (item[0][0], item[1]))
        for ordinal, (paragraphs, _, event, quote) in enumerate(accepted, start=1):
            covers = tuple(blocks[number - 1].block_id for number in paragraphs)
            scene = scene_of.get(covers[0])
            actuality: EventActuality = event.actuality
            if actuality == "present" and scene is not None and scene.flashback:
                actuality = "flashback"
            uses = [use for use in event.uses if normalize_name(use.actor) and normalize_name(use.thing)]
            draft = ItemDraft(
                local_key=f"event{ordinal}",
                table="event",
                fields={
                    "ordinal": ordinal, "scene_key": scene.scene_key if scene is not None else None,
                    "actuality": actuality, "summary": event.summary.strip(),
                },
                names={
                    "present": _characters(event.present),
                    "mentioned": _characters(event.mentioned),
                    "use_actors": tuple(EntityName(kind="character", name=use.actor.strip()) for use in uses),
                    "use_things": tuple(EntityName(kind=use.thing_kind, name=use.thing.strip()) for use in uses),
                },
                quotes=(quote,),
                covers_blocks=covers,
            )
            drafts.append(draft)
            by_key.setdefault(event.key.strip(), draft)
        prior = {event.label: event for event in slot_input.prior}
        for number, relation in enumerate(output.relations, start=1):
            source = by_key.get(relation.event.strip())
            target = prior.get(relation.target.strip())
            if source is None:
                dropped["relation_event_unknown"] += 1
            elif source.fields["actuality"] != "flashback":
                dropped["relation_not_flashback"] += 1
            elif target is None:
                dropped["relation_target_unknown"] += 1
            elif target.target_block_id is None:
                dropped["relation_target_ambiguous"] += 1
            else:
                drafts.append(
                    ItemDraft(
                        local_key=f"relation{number}",
                        table="event_relation",
                        fields={
                            "event": source.local_key, "relation": relation.relation,
                            "to_anchor_block_id": str(target.target_block_id), "to_chapter_id": str(target.chapter_id),
                        },
                        # 관계의 근거는 그 회상 사건의 인용이다 — 관계 자체를 따로 인용하게 하지 않는다.
                        quotes=source.quotes,
                    )
                )
        return Proposal(items=tuple(drafts), dropped=dict(dropped))

    def _records(
        self, items: Sequence[LinkedItem], commit: CommitRef, revision_id: uuid.UUID
    ) -> tuple[list[NovelBibleEvent], list[NovelBibleEventRelation]]:
        common = {"novel_id": commit.novel_id, "chapter_id": commit.chapter_id, "created_revision_id": revision_id}
        events: list[NovelBibleEvent] = []
        event_ids: dict[str, uuid.UUID] = {}
        for item in items:
            if item.draft.table != "event":
                continue
            fields, entity_ids = item.draft.fields, item.entity_ids
            event_ids[item.draft.local_key] = item.id
            uses = zip(entity_ids.get("use_actors", ()), entity_ids.get("use_things", ()), strict=True)
            events.append(
                NovelBibleEvent(
                    id=item.id, ordinal=fields["ordinal"], scene_key=fields["scene_key"],
                    actuality=fields["actuality"], summary=fields["summary"],
                    anchor_block_ids=list(item.draft.covers_blocks),
                    present_entity_ids=_unique(entity_ids.get("present", ())),
                    mentioned_entity_ids=_unique(entity_ids.get("mentioned", ())),
                    uses=[{"actor": str(actor), "thing": str(thing)} for actor, thing in uses],
                    **common,
                )
            )
        relations = [
            NovelBibleEventRelation(
                id=item.id, from_event_id=event_ids[item.draft.fields["event"]],
                relation=item.draft.fields["relation"],
                to_anchor_block_id=uuid.UUID(item.draft.fields["to_anchor_block_id"]),
                to_chapter_id=uuid.UUID(item.draft.fields["to_chapter_id"]),
                **common,
            )
            for item in items
            if item.draft.table == "event_relation"
        ]
        return events, relations

    async def apply(
        self, session: AsyncSession, items: Sequence[LinkedItem], commit: CommitRef, at: RevisionRef
    ) -> None:
        assert at.id is not None
        events, relations = self._records(items, commit, at.id)
        # 회상 관계가 사건 행을 FK 로 가리키므로 사건을 먼저 넣는다.
        session.add_all(events)
        await session.flush()
        session.add_all(relations)
        await session.flush()

    def rows(self, items: Sequence[LinkedItem], commit: CommitRef) -> SlotRows:
        events, relations = self._records(items, commit, uuid.uuid4())
        return (
            *(_event_row(event, commit.chapter_ordinal) for event in events),
            *(_relation_row(relation) for relation in relations),
        )

    async def current_item_ids(
        self, session: AsyncSession, novel_id: uuid.UUID, chapter_id: uuid.UUID, at: RevisionRef
    ) -> list[tuple[ItemTable, uuid.UUID]]:
        found: list[tuple[ItemTable, uuid.UUID]] = []
        for table, model in _TABLES:
            statement = current_items(model, table, novel_id, at).where(model.chapter_id == chapter_id)
            found += [(table, row.id) for row in (await session.scalars(statement)).all()]
        return found

    async def read(self, session: AsyncSession, novel_id: uuid.UUID, at: RevisionRef) -> SlotRows:
        events = (
            await session.execute(
                current_items(NovelBibleEvent, "event", novel_id, at)
                .add_columns(NovelChapter.ordinal)
                .join(NovelChapter, NovelChapter.id == NovelBibleEvent.chapter_id)
            )
        ).all()
        relations = (
            await session.scalars(current_items(NovelBibleEventRelation, "event_relation", novel_id, at))
        ).all()
        return (
            *(_event_row(event, ordinal) for event, ordinal in events),
            *(_relation_row(relation) for relation in relations),
        )
