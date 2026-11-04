"""지식 슬롯 — 확정 원고에서 인물이 명제 하나를 안다(`knows`)거나 믿는다(`believes`)를 뽑아 지식 표에 쓴다.

입력은 확정 개정의 문단(번호만 — 장면 경계 표시는 싣지 않는다)과 아는 개체뿐이다. 아는 개체는 정본 상태에서 오는 힌트라 추출
캐시 열쇠에서 빠진다. 장면 구성안은 싣지 않는다 — 계획은 확정된 원고가 아니라, 거기서 뽑으면 원고에 없는 앎이 정본이 된다. 원문
채팅 구간과 채팅 기억도 읽지 않는다 — 플레이와의 차이는 사실 슬롯이 채팅 기억 사실로 본다.

앎 주체(아는 인물)와 명제의 주어(무엇에 대한 앎인가)는 출력에서도 다른 칸이고, 앎 주체는 늘 인물로 `names["knower"]` 에, 명제의
주어는 명제의 주어 종류로 `names["subject"]` 에 따로 싣는다. 명제 칸은 사실 슬롯과 같은 코어 규칙(`core/keys.py`)으로 검증하고
다듬어, 같은 명제면 사실 행과 같은 안정 키를 받는다. 키는 명제만으로 계산되므로 사실 슬롯이 꺼져 있어도 저장되고, 사실이 같은
키의 새 행으로 대체돼도 읽을 때 이어진다. 믿음은 사실 행에 붙인 표시가 아니라 명제 하나다 — 원고의 사실과 다른 내용(거짓 믿음)은
사실 행으로 나타낼 수 없기 때문이다. 명제는 사실 하나뿐이라 앎에 대한 앎(고차 믿음)은 담지 않는다.

꿈·상상 장면에서 생긴 앎도 버리지 않는다 — 그 장면이 꿈이라는 것은 알게 된 사건의 현실성이 가지고, 앎은 그 사건에 이어져 그
정보를 잃지 않는다.

다른 슬롯을 모른다 — 지식 표에만 쓰고, 앎이 사건에 이어지는 것은 코어의 연결 단계가 인용 블록으로 푼다."""

import uuid
from collections import Counter
from collections.abc import Sequence
from typing import Any

from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.models.novel_bible_knowledge import NovelBibleKnowledge
from api.novel_bible.core.contracts import CoreReadView
from api.novel_bible.core.keys import (
    TARGETED_KINDS,
    make_proposition,
    normalize_name,
    predicate_norm,
    proposition_names,
    proposition_problem,
)
from api.novel_bible.core.known import known_entities_text
from api.novel_bible.core.queries import current_items
from api.novel_bible.core.quotes import verify_quote
from api.novel_bible.core.types import (
    CommitRef,
    EntityName,
    ItemDraft,
    KnowledgeRow,
    LinkedItem,
    Manuscript,
    Proposal,
    RevisionRef,
    SlotRows,
)
from api.novel_bible.ids import ItemTable, OperationKey, SlotId
from api.novel_bible.slots.knowledge.schema import KnowledgeOutput


class KnowledgeInput(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True)

    manuscript: Manuscript
    known: list[EntityName]


def _knowledge_row(row: NovelBibleKnowledge) -> KnowledgeRow:
    return KnowledgeRow(
        id=row.id, chapter_id=row.chapter_id, knower_entity_id=row.knower_entity_id, kind=row.kind,
        fact_key=row.fact_key, proposition=dict(row.proposition), known_since_event_id=row.known_since_event_id,
    )


class KnowledgeSlot:
    """지식 슬롯. 검증은 항목 하나씩 버리고 버린 수를 사유별로 센다 — 출력 전체가 스키마에 맞지 않으면 구조화 호출이 실패해 이
    검증까지 오지 않는다."""

    id: SlotId = "knowledge"
    operation: OperationKey = "knowledge.extract"
    channel: str = "novel_bible_knowledge"
    output_schema: type[BaseModel] = KnowledgeOutput
    tables: frozenset[ItemTable] = frozenset({"knowledge"})
    hint_values: frozenset[str] = frozenset({"known_entities"})

    async def build_input(self, session: AsyncSession, view: CoreReadView) -> KnowledgeInput:
        return KnowledgeInput(manuscript=await view.manuscript(), known=await view.known_entities())

    def prompt_values(self, slot_input: BaseModel) -> dict[str, str]:
        """렌더 값 둘(지시문 섹션 `instruction` 은 값이 없다). 값의 꼴은 이 함수가 정하고, 문안 채널 `novel_bible_knowledge` 의
        지시문이 이 꼴을 모델에게 설명해야 한다 — 꼴을 모르는 지시문은 오류 없이 문단 번호·이름을 틀리게 만든다.

        - `manuscript`: 문단마다 한 줄 `[번호] 글`. 장면 경계 표시는 없다(사실 슬롯과 같은 꼴). 모델이 내는 `quote.paragraph` 는
          `[번호]` 의 번호이고, `quote.text` 는 `[번호] ` 머리 없이 그 문단 글에서 그대로 옮긴 구절이어야 한다 — 인용 검증이 문단
          글에서 찾는다.
        - `known_entities`: 사건·사실 슬롯과 같은 글이다 — 꼴은 `core/known.py` 의 `known_entities_text`. 앎 주체·명제의 주어·대상
          이름을 낼 때는 이름만 쓴다.

        출력에서 앎 주체(`knower`)와 명제의 주어(`about.subject`)는 다른 칸이다 — 지시문이 둘의 방향을 예로 보여야 한다
        (`schema.py` 모듈 docstring)."""
        assert isinstance(slot_input, KnowledgeInput)
        return {
            "manuscript": "\n".join(f"[{block.index}] {block.text}" for block in slot_input.manuscript.blocks),
            "known_entities": known_entities_text(slot_input.known),
        }

    def validate(self, slot_input: BaseModel, output: BaseModel) -> Proposal:
        """지식: 인용 구절이 그 문단에 없으면, 명제 칸이 사실과 같은 규칙에 어긋나면(생사·출입 값이 정해진 값이 아님, 값이 빔,
        유지가 거짓인데 종류가 생사·출입·속성, 속성·관계 이름이 빔) 버린다. 앎 주체 이름이 비면 코어가 저장 전에 버린다."""
        assert isinstance(slot_input, KnowledgeInput) and isinstance(output, KnowledgeOutput)
        dropped: Counter[str] = Counter()
        drafts: list[ItemDraft] = []
        for item in output.items:
            quote = verify_quote(slot_input.manuscript, item.quote)
            if quote is None:
                dropped["quote_not_found"] += 1
                continue
            about = item.about
            if (problem := proposition_problem(about.kind, about.attribute, about.value, about.holds)) is not None:
                dropped[problem] += 1
                continue
            proposition = make_proposition(
                about.subject, about.subject_kind, about.kind, about.attribute, about.value, about.holds
            )
            drafts.append(
                ItemDraft(
                    local_key=f"knowledge{len(drafts) + 1}",
                    table="knowledge",
                    fields={"kind": item.kind},
                    names={
                        "knower": (EntityName(kind="character", name=item.knower.strip()),),
                        **proposition_names(proposition),
                    },
                    quotes=(quote,),
                    anchor_block=quote.block_id,
                    proposition=proposition,
                )
            )
        return Proposal(items=tuple(drafts), dropped=dict(dropped))

    def _records(
        self, items: Sequence[LinkedItem], commit: CommitRef, revision_id: uuid.UUID
    ) -> list[NovelBibleKnowledge]:
        records: list[NovelBibleKnowledge] = []
        for item in items:
            proposition = item.draft.proposition
            assert proposition is not None and item.fact_key is not None  # 지식 초안은 늘 명제가 있고 코어가 키를 푼다
            value_entity = item.entity_ids["value"][0] if proposition.kind in TARGETED_KINDS else None
            # 명제 칸은 사실 행의 같은 이름 칸과 같은 값이다 — 이 칸들만으로 안정 키를 다시 계산할 수 있다.
            stored: dict[str, Any] = {
                "subject_entity_id": str(item.entity_ids["subject"][0]), "kind": proposition.kind,
                "predicate_norm": predicate_norm(proposition.kind, proposition.attribute), "value": proposition.value,
                "value_norm": normalize_name(proposition.value),
                "value_entity_id": str(value_entity) if value_entity is not None else None,
                "holds": proposition.holds,
            }
            records.append(
                NovelBibleKnowledge(
                    id=item.id, novel_id=commit.novel_id, chapter_id=commit.chapter_id, created_revision_id=revision_id,
                    supersedes_id=item.supersedes_id, knower_entity_id=item.entity_ids["knower"][0],
                    kind=item.draft.fields["kind"], fact_key=item.fact_key, proposition=stored,
                    known_since_event_id=item.event_id,
                )
            )
        return records

    async def apply(
        self, session: AsyncSession, items: Sequence[LinkedItem], commit: CommitRef, at: RevisionRef
    ) -> None:
        assert at.id is not None
        session.add_all(self._records(items, commit, at.id))
        await session.flush()

    def rows(self, items: Sequence[LinkedItem], commit: CommitRef) -> SlotRows:
        return tuple(_knowledge_row(row) for row in self._records(items, commit, uuid.uuid4()))

    async def current_item_ids(
        self, session: AsyncSession, novel_id: uuid.UUID, chapter_id: uuid.UUID, at: RevisionRef
    ) -> list[tuple[ItemTable, uuid.UUID]]:
        statement = current_items(NovelBibleKnowledge, "knowledge", novel_id, at).where(
            NovelBibleKnowledge.chapter_id == chapter_id
        )
        return [("knowledge", row.id) for row in (await session.scalars(statement)).all()]

    async def read(self, session: AsyncSession, novel_id: uuid.UUID, at: RevisionRef) -> SlotRows:
        rows = (await session.scalars(current_items(NovelBibleKnowledge, "knowledge", novel_id, at))).all()
        return tuple(_knowledge_row(row) for row in rows)
