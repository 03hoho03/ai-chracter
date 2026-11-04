"""사실 슬롯 — 확정 원고에서 상태·속성·관계 명제(생사·출입·소지·능력·속성·관계)를 뽑아 사실 표에 쓴다.

입력은 확정 개정의 문단(번호만 — 장면 경계 표시는 싣지 않는다), 아는 개체, 이미 정본인 불변 속성, 원작 정본(작품 설정·키워드
노트), 플레이 사실(그 소설이 나온 방의 채팅 기억 사실)이다. 아는 개체와 정본 불변 속성은 정본 상태에서 오는 힌트라 추출 캐시
열쇠에서 빠지고, 원작·플레이 사실은 화 고유 입력이라 열쇠에 든다. 장면 구성안은 싣지 않는다 — 계획은 확정된 원고가 아니라, 거기서
뽑으면 원고에 없는 내용이 정본이 된다. 원문 채팅 구간도 읽지 않는다 — 플레이와의 차이는 채팅 기억 사실로 본다. 플레이 사실은
채팅 기억 스위치와 무관하게 읽고(코어 읽기 뷰의 `play_facts`), 방이 없으면 그 섹션이 빠진다.

정본은 원고다. 원작·플레이와 다른 사실도 그대로 확정 사실로 커밋되고, 모델이 짚은 차이는 근거(`side_quotes`)로 실려 코어가 각색
후보 행과 그 근거 행을 쓴다 — 차단이 아니다. 차이의 근거가 틀리면(표지가 없음, 구절이 그 글에 없음) 차이만 버리고 사실은 남긴다.

`onset` 은 이 장면에서 상태가 시작됐다고 서술됐는가다(얻음·배움·일어남·돌아옴). 사실이 이어지는 사건은 시작 자리가 아니라 처음
인용한 자리라, 늦게 드러난 기존 상태("오래 지니던 검")를 시작으로 읽지 않으려고 따로 받는다. 작품 전체 범위에는 시작 자리가 없어
거짓으로 고친다. 불변 속성은 작품 전체 범위로 둔다. 속성 값은 인물 이름이어도 개체에 잇지 않는다 — 이으면 그 이름의 개체가
먼저 생겼느냐에 따라 같은 명제의 안정 키가 달라진다. 주어는 인물이다. 대상이 개체인 종류(소지·능력·관계)만 대상을 개체(사물·
능력·인물)로 잇는다.

다른 슬롯을 모른다 — 사실 표에만 쓰고, 사실이 사건에 이어지는 것은 코어의 연결 단계가 인용 블록으로 푼다."""

import uuid
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from typing import get_args

from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.models.novel_bible import NovelBibleEntity
from api.db.models.novel_bible_facts import NovelBibleFact
from api.novel_bible.core.contracts import CoreReadView
from api.novel_bible.core.keys import TARGETED_KINDS, normalize_name, predicate_norm
from api.novel_bible.core.known import known_entities_text
from api.novel_bible.core.queries import current_items, revision_at
from api.novel_bible.core.quotes import quote_hash, verify_quote
from api.novel_bible.core.types import (
    CommitRef,
    EntityName,
    FactRow,
    ItemDraft,
    LinkedItem,
    Manuscript,
    PlayFact,
    Proposal,
    Proposition,
    RevisionRef,
    SideQuote,
    SlotRows,
    SourceCanon,
)
from api.novel_bible.ids import (
    EntityKind,
    FactKind,
    FactScope,
    ItemTable,
    LifeValue,
    OperationKey,
    PresenceValue,
    SlotId,
    SourceField,
)
from api.novel_bible.slots.facts.schema import ExtractedFact, FactsOutput, SourceDifference

# 대상이 개체인 종류의 대상 개체 종류.
_VALUE_ENTITY_KINDS: dict[FactKind, EntityKind] = {"possession": "object", "ability": "ability", "relation": "character"}
# 값이 정해진 목록 안에 있어야 하는 종류.
_CLOSED_VALUES: dict[FactKind, frozenset[str]] = {
    "life": frozenset(get_args(LifeValue)),
    "presence": frozenset(get_args(PresenceValue)),
}
# 술어가 속성·관계 이름인 종류.
_NAMED_PREDICATE: frozenset[FactKind] = frozenset({"attribute", "relation"})
_WORK_SETTING_LABEL = "S"
_CLAIMED_TAIL = " (주장)"


@dataclass(frozen=True)
class KnownAttribute:
    """이미 정본인 불변 속성 하나 — 같은 값이면 같은 표기를 쓰게 보여 준다. 속성은 정규화한 술어다."""

    subject: str
    attribute: str
    value: str


class FactsInput(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True)

    manuscript: Manuscript
    known: list[EntityName]
    known_attributes: list[KnownAttribute]
    source: SourceCanon | None
    play: list[PlayFact] | None


@dataclass(frozen=True)
class _SourceText:
    text: str
    field: SourceField
    keyword_note_id: uuid.UUID | None


def _source_texts(canon: SourceCanon | None) -> dict[str, _SourceText]:
    """표지마다 원작 글 — 작품 설정은 `S`(비면 없음), 키워드 노트는 원작 슬롯이 준 차례대로 `K1`·`K2` …."""
    if canon is None:
        return {}
    texts: dict[str, _SourceText] = {}
    if canon.work_setting.strip():
        texts[_WORK_SETTING_LABEL] = _SourceText(canon.work_setting, "work_setting", None)
    for number, (note_id, text) in enumerate(canon.keyword_notes.items(), start=1):
        texts[f"K{number}"] = _SourceText(text, "keyword_note", note_id)
    return texts


def _play_labels(play: Sequence[PlayFact] | None) -> dict[str, PlayFact]:
    return {f"P{number}": fact for number, fact in enumerate(play or (), start=1)}


def _play_line(label: str, fact: PlayFact) -> str:
    if fact.object is not None:
        body = f"{fact.subject} → {fact.object}: {fact.value}"
    else:
        body = f"{fact.subject} · {fact.attribute}: {fact.value}"
    return f"{label}. {body}" + (_CLAIMED_TAIL if fact.claimed else "")


async def _known_attributes(session: AsyncSession, commit: CommitRef, manuscript: Manuscript) -> list[KnownAttribute]:
    """지금 머리 시점에 현재인 불변 속성 중 주어 개체의 이름이나 별칭이 이 화 원고에 나오는 것(정규화한 글의 부분 문자열)."""
    head = await revision_at(session, commit.novel_id, None)
    rows = (
        await session.execute(
            current_items(NovelBibleFact, "fact", commit.novel_id, head)
            .add_columns(NovelBibleEntity.name, NovelBibleEntity.aliases)
            .join(NovelBibleEntity, NovelBibleEntity.id == NovelBibleFact.subject_entity_id)
            .where(NovelBibleFact.kind == "attribute", NovelBibleFact.immutable.is_(True))
        )
    ).all()
    text = normalize_name("\n".join(block.text for block in manuscript.blocks))
    found = {
        KnownAttribute(subject=name, attribute=fact.predicate_norm, value=fact.value)
        for fact, name, aliases in rows
        if any(norm and norm in text for norm in map(normalize_name, (name, *aliases)))
    }
    return sorted(found, key=lambda known: (known.subject, known.attribute, known.value))


def _problem(fact: ExtractedFact) -> str | None:
    """항목을 버릴 사유 — 값이 종류에 맞지 않음, 값이 빔, 유지가 거짓일 수 없는 종류, 속성·관계 이름이 빔, 속성이 아닌 불변."""
    value = normalize_name(fact.value)
    closed = _CLOSED_VALUES.get(fact.kind)
    if closed is not None and value not in closed:
        return "value_invalid"
    if not value:
        return "value_empty"
    if not fact.holds and fact.kind not in TARGETED_KINDS:
        return "holds_invalid"
    if fact.kind in _NAMED_PREDICATE and not normalize_name(fact.attribute):
        return "attribute_missing"
    if fact.immutable and fact.kind != "attribute":
        return "immutable_not_attribute"
    return None


def _source_side(
    difference: SourceDifference, texts: dict[str, _SourceText], canon: SourceCanon | None
) -> SideQuote | None:
    source = texts.get(difference.label.strip())
    if canon is None or source is None or not difference.quote:
        return None
    start = source.text.find(difference.quote)
    if start < 0:
        return None
    return SideQuote(
        origin="source_canon", content_version_id=canon.ref.content_version_id, source_field=source.field,
        keyword_note_id=source.keyword_note_id, char_start=start, char_end=start + len(difference.quote),
        quote_sha256=quote_hash(difference.quote),
    )


def _fact_row(fact: NovelBibleFact) -> FactRow:
    return FactRow(
        id=fact.id, chapter_id=fact.chapter_id, fact_key=fact.fact_key, subject_entity_id=fact.subject_entity_id,
        kind=fact.kind, predicate_norm=fact.predicate_norm, value=fact.value, value_norm=fact.value_norm,
        value_entity_id=fact.value_entity_id, holds=fact.holds, immutable=fact.immutable, onset=fact.onset,
        scope=fact.scope, valid_from_event_id=fact.valid_from_event_id,
    )


class FactsSlot:
    """사실 슬롯. 검증은 항목 하나씩 버리고 버린 수를 사유별로 센다 — 출력 전체가 스키마에 맞지 않으면 구조화 호출이 실패해 이
    검증까지 오지 않는다."""

    id: SlotId = "facts"
    operation: OperationKey = "facts.extract"
    channel: str = "novel_bible_facts"
    output_schema: type[BaseModel] = FactsOutput
    tables: frozenset[ItemTable] = frozenset({"fact"})
    hint_values: frozenset[str] = frozenset({"known_entities", "known_attributes"})

    async def build_input(self, session: AsyncSession, view: CoreReadView) -> FactsInput:
        manuscript = await view.manuscript()
        return FactsInput(
            manuscript=manuscript,
            known=await view.known_entities(),
            known_attributes=await _known_attributes(session, view.commit, manuscript),
            source=await view.source_canon(),
            play=await view.play_facts(),
        )

    def prompt_values(self, slot_input: BaseModel) -> dict[str, str]:
        """렌더 값 다섯(지시문 섹션 `instruction` 은 값이 없다). 값의 꼴은 이 함수가 정하고, 문안 채널 `novel_bible_facts` 의
        지시문이 이 꼴을 모델에게 설명해야 한다 — 꼴을 모르는 지시문은 오류 없이 문단 번호·표지·이름을 틀리게 만든다.

        - `manuscript`: 문단마다 한 줄 `[번호] 글`. 장면 경계 표시는 없다. 모델이 내는 `quote.paragraph` 는 `[번호]` 의 번호이고,
          `quote.text` 는 `[번호] ` 머리 없이 그 문단 글에서 그대로 옮긴 구절이어야 한다 — 인용 검증이 문단 글에서 찾는다.
        - `known_entities`: 사건 슬롯과 같은 글이다 — 꼴은 `core/known.py` 의 `known_entities_text`.
        - `known_attributes`: 이미 정본인 불변 속성마다 한 줄 `- 주어 · 속성: 값`(속성은 정규화한 이름), 같은 줄은 한 번만
          글자 순으로. 같은 값이면 이 표기를 그대로 쓰게 하는 힌트다 — 표기가 다르면 같은 값도 다른 값으로 읽힌다.
        - `source_canon`: 원작 글마다 `[표지] 글` 한 덩이, 덩이 사이는 빈 줄. 표지는 작품 설정 `S`, 키워드 노트 `K1`·`K2` …. 글
          안에 줄바꿈이 있을 수 있다. 차이를 낼 때 `source_difference.label` 은 표지(`S`·`K1`)만, `quote` 는 `[표지] ` 머리 없이
          그 글에서 그대로 옮긴 구절이다 — 표지가 없거나 구절이 그 글에 없으면 차이만 버린다.
        - `play_facts`: 플레이 사실마다 한 줄 `P1. 주어 → 대상: 값`(관계) 또는 `P1. 주어 · 속성: 값`(속성), 말한 사람만 그렇다고
          한 주장이면 끝에 ` (주장)`. `play_difference.ref` 는 표지(`P1`)만 받는다 — 앞뒤 공백 말고 다른 글자가 붙으면 차이를
          버린다.

        원작·플레이 사실이 없으면 그 값은 빈 글이다(문안이 그 섹션을 조건부로 두면 섹션째 빠진다)."""
        assert isinstance(slot_input, FactsInput)
        return {
            "manuscript": "\n".join(f"[{block.index}] {block.text}" for block in slot_input.manuscript.blocks),
            "known_entities": known_entities_text(slot_input.known),
            "known_attributes": "\n".join(
                sorted({f"- {known.subject} · {known.attribute}: {known.value}" for known in slot_input.known_attributes})
            ),
            "source_canon": "\n\n".join(
                f"[{label}] {source.text}" for label, source in _source_texts(slot_input.source).items()
            ),
            "play_facts": "\n".join(_play_line(label, fact) for label, fact in _play_labels(slot_input.play).items()),
        }

    def validate(self, slot_input: BaseModel, output: BaseModel) -> Proposal:
        """사실: 인용 구절이 그 문단에 없으면, 생사·출입 값이 정해진 값이 아니면, 값이 비면, 유지가 거짓인데 종류가 생사·출입·
        속성이면, 속성·관계 이름이 비면, 속성이 아닌데 불변이면 버린다. 불변이면 작품 전체 범위로, 작품 전체 범위면 시작을 거짓으로
        고친다. 원작·플레이 차이는 근거가 맞을 때만 남기고, 틀리면 차이만 버린다(사실은 남긴다)."""
        assert isinstance(slot_input, FactsInput) and isinstance(output, FactsOutput)
        sources = _source_texts(slot_input.source)
        plays = _play_labels(slot_input.play)
        dropped: Counter[str] = Counter()
        drafts: list[ItemDraft] = []
        for fact in output.facts:
            quote = verify_quote(slot_input.manuscript, fact.quote)
            if quote is None:
                dropped["quote_not_found"] += 1
                continue
            if (problem := _problem(fact)) is not None:
                dropped[problem] += 1
                continue
            scope: FactScope = "work" if fact.immutable else fact.scope
            value = normalize_name(fact.value) if fact.kind in _CLOSED_VALUES else fact.value.strip()
            proposition = Proposition(
                subject=fact.subject.strip(), kind=fact.kind,
                attribute=(fact.attribute or "").strip() if fact.kind in _NAMED_PREDICATE else None,
                value=value, holds=fact.holds,
            )
            names: dict[str, tuple[EntityName, ...]] = {
                "subject": (EntityName(kind="character", name=proposition.subject),)
            }
            if fact.kind in _VALUE_ENTITY_KINDS:
                names["value"] = (EntityName(kind=_VALUE_ENTITY_KINDS[fact.kind], name=value),)
            sides: list[SideQuote] = []
            if fact.source_difference is not None:
                side = _source_side(fact.source_difference, sources, slot_input.source)
                if side is None:
                    dropped["source_difference_dropped"] += 1
                else:
                    sides.append(side)
            if fact.play_difference is not None:
                played = plays.get(fact.play_difference.ref.strip())
                if played is None:
                    dropped["play_difference_dropped"] += 1
                else:
                    sides.append(
                        SideQuote(
                            origin="play", chat_room_id=played.chat_room_id,
                            chat_memory_fact_id=played.chat_memory_fact_id, chat_fact_key=played.chat_fact_key,
                        )
                    )
            drafts.append(
                ItemDraft(
                    local_key=f"fact{len(drafts) + 1}",
                    table="fact",
                    fields={"immutable": fact.immutable, "onset": fact.onset and scope != "work", "scope": scope},
                    names=names,
                    quotes=(quote,),
                    anchor_block=quote.block_id,
                    proposition=proposition,
                    side_quotes=tuple(sides),
                )
            )
        return Proposal(items=tuple(drafts), dropped=dict(dropped))

    def _records(self, items: Sequence[LinkedItem], commit: CommitRef, revision_id: uuid.UUID) -> list[NovelBibleFact]:
        records: list[NovelBibleFact] = []
        for item in items:
            proposition = item.draft.proposition
            assert proposition is not None and item.fact_key is not None  # 사실 초안은 늘 명제가 있고 코어가 키를 푼다
            fields = item.draft.fields
            records.append(
                NovelBibleFact(
                    id=item.id, novel_id=commit.novel_id, chapter_id=commit.chapter_id, created_revision_id=revision_id,
                    supersedes_id=item.supersedes_id, fact_key=item.fact_key,
                    subject_entity_id=item.entity_ids["subject"][0], kind=proposition.kind,
                    predicate_norm=predicate_norm(proposition.kind, proposition.attribute), value=proposition.value,
                    value_norm=normalize_name(proposition.value),
                    value_entity_id=item.entity_ids["value"][0] if proposition.kind in TARGETED_KINDS else None,
                    holds=proposition.holds, immutable=fields["immutable"], onset=fields["onset"],
                    scope=fields["scope"], valid_from_event_id=item.event_id,
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
        return tuple(_fact_row(fact) for fact in self._records(items, commit, uuid.uuid4()))

    async def current_item_ids(
        self, session: AsyncSession, novel_id: uuid.UUID, chapter_id: uuid.UUID, at: RevisionRef
    ) -> list[tuple[ItemTable, uuid.UUID]]:
        statement = current_items(NovelBibleFact, "fact", novel_id, at).where(NovelBibleFact.chapter_id == chapter_id)
        return [("fact", fact.id) for fact in (await session.scalars(statement)).all()]

    async def read(self, session: AsyncSession, novel_id: uuid.UUID, at: RevisionRef) -> SlotRows:
        facts = (await session.scalars(current_items(NovelBibleFact, "fact", novel_id, at))).all()
        return tuple(_fact_row(fact) for fact in facts)
