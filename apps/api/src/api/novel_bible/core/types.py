"""정본 기억 코어와 슬롯·규칙이 주고받는 값.

슬롯의 검증 결과(`Proposal`)는 작업 행의 `proposal` 칸에 JSON 으로 저장됐다가 커밋 때 다시 읽히므로 pydantic 모델이다(그대로
왕복한다). 슬롯끼리 같은 꼴을 써야 하는 것(명제·개체 이름)도 슬롯이 서로 import 하지 않게 여기 둔다. 규칙과 시점 질의는 표가
아니라 아래 행 타입만 읽는다."""

import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict

from api.novel_bible.ids import (
    AdaptationOrigin,
    EntityKind,
    EventActuality,
    EventRelationKind,
    FactKind,
    FactScope,
    FindingRule,
    FindingSeverity,
    ItemTable,
    KnowledgeKind,
    SourceField,
)


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True)


class QuoteOut(BaseModel):
    """모델이 내는 근거 인용. `paragraph` 는 프롬프트에 보인 문단 번호(1부터), `text` 는 그 문단에서 그대로 옮긴 구절."""

    paragraph: int
    text: str


class EntityName(_Frozen):
    """개체 하나의 이름. 연결 단계가 (종류, 정규 이름)으로 개체 id 를 찾거나 만든다. 별칭은 힌트로 보여 줄 때만 쓴다."""

    kind: EntityKind
    name: str
    aliases: tuple[str, ...] = ()


class Proposition(_Frozen):
    """사실 슬롯과 지식 슬롯이 같은 꼴로 쓰는 명제. 안정 키(`keys.fact_key`)가 이 칸들에서 나온다."""

    subject: str
    kind: FactKind
    attribute: str | None
    value: str
    holds: bool


class VerifiedQuote(_Frozen):
    """원고 블록 글 안의 구간과 그 구간 글의 sha256. 인용 글 자체는 저장하지 않는다."""

    block_id: uuid.UUID
    char_start: int
    char_end: int
    quote_sha256: str


class SideQuote(_Frozen):
    """원작 정본이나 플레이(채팅 기억)에서 온 근거 — 그 근거가 붙은 사실은 각색 후보가 된다. 원작이면 버전·자리·구간·해시를,
    플레이면 방·채팅 기억 행·그 키를 채운다."""

    origin: AdaptationOrigin
    content_version_id: uuid.UUID | None = None
    source_field: SourceField | None = None
    keyword_note_id: uuid.UUID | None = None
    char_start: int | None = None
    char_end: int | None = None
    quote_sha256: str | None = None
    chat_room_id: uuid.UUID | None = None
    chat_memory_fact_id: uuid.UUID | None = None
    chat_fact_key: str | None = None


class ItemDraft(_Frozen):
    """검증을 통과한 항목 하나. `fields` 는 슬롯만 해석하고 JSON 으로 저장될 수 있는 값만 담는다. 코어가 푸는 칸은 이름
    (`names`), 근거(`quotes`, 하나 이상), 사건 연결 앵커(`anchor_block`), 사건이 걸친 블록(`covers_blocks`, 사건만), 명제
    (`proposition`), 원작·플레이 근거(`side_quotes`)뿐이다.

    지식 항목은 앎 주체를 `names["knower"]`, 앎 종류를 `fields["kind"]` 에 둔다 — 같은 화의 이전 지식 행을 대체할 때 코어가
    (앎 주체, 종류, 키)로 짝을 찾는다."""

    local_key: str
    table: ItemTable
    fields: dict[str, Any]
    names: dict[str, tuple[EntityName, ...]] = {}
    quotes: tuple[VerifiedQuote, ...]
    anchor_block: uuid.UUID | None = None
    covers_blocks: tuple[uuid.UUID, ...] = ()
    proposition: Proposition | None = None
    side_quotes: tuple[SideQuote, ...] = ()


class Proposal(_Frozen):
    items: tuple[ItemDraft, ...]
    # 버린 항목 수(사유별) — 인용이 문단에 없음·값이 종류에 맞지 않음 따위.
    dropped: dict[str, int] = {}


@dataclass(frozen=True)
class LinkedItem:
    """연결을 마친 항목. `id` 는 코어가 미리 정한 행 id 이고, 사건·사실 키·대체 대상이 풀려 있다. 사건이 없으면(사건 슬롯이
    빠졌거나 이번 확정에 사건이 0개) `event_id` 는 None — 미정이다."""

    id: uuid.UUID
    draft: ItemDraft
    entity_ids: Mapping[str, tuple[uuid.UUID, ...]]
    event_id: uuid.UUID | None
    fact_key: uuid.UUID | None
    supersedes_id: uuid.UUID | None


@dataclass(frozen=True)
class RevisionRef:
    """정본 기억 리비전 하나. 번호는 소설의 canon 가지 안 번호이고 0 은 리비전이 없는 상태다. 새로 넣을 리비전을 가리킬 때도
    쓴다(그때 `id` 가 새 행의 id)."""

    id: uuid.UUID | None
    revision_no: int


@dataclass(frozen=True)
class CommitRef:
    """확정 하나가 무엇을 확정하는가. `scope` 는 문안 섹션을 고르는 축(`character`·`story`)으로 소설 원작의 종류에서 온다."""

    commit_id: uuid.UUID
    novel_id: uuid.UUID
    chapter_id: uuid.UUID
    chapter_revision_id: uuid.UUID
    chapter_ordinal: int
    scope: str


@dataclass(frozen=True)
class ManuscriptBlock:
    index: int  # 1부터 — 프롬프트에 보이는 문단 번호
    block_id: uuid.UUID
    text: str


@dataclass(frozen=True)
class Manuscript:
    revision_id: uuid.UUID
    blocks: tuple[ManuscriptBlock, ...]


@dataclass(frozen=True)
class SourceCanonRef:
    """원작 정본의 버전과 그 글의 해시 — 확정 행에 남겨 작업 때 같은 글을 다시 만든다."""

    content_version_id: uuid.UUID
    input_hash: str


@dataclass(frozen=True)
class SourceCanon:
    ref: SourceCanonRef
    work_setting: str
    keyword_notes: Mapping[uuid.UUID, str]


@dataclass(frozen=True)
class RenderedPrompt:
    system_instruction: str
    prompt: str
    prompt_set_id: uuid.UUID


@dataclass(frozen=True)
class EventRow:
    id: uuid.UUID
    chapter_id: uuid.UUID
    chapter_ordinal: int
    ordinal: int
    actuality: EventActuality
    anchor_block_ids: tuple[uuid.UUID, ...]


@dataclass(frozen=True)
class RelationRow:
    id: uuid.UUID
    chapter_id: uuid.UUID
    from_event_id: uuid.UUID
    relation: EventRelationKind
    to_anchor_block_id: uuid.UUID
    to_chapter_id: uuid.UUID


@dataclass(frozen=True)
class FactRow:
    id: uuid.UUID
    chapter_id: uuid.UUID
    fact_key: uuid.UUID
    subject_entity_id: uuid.UUID
    kind: FactKind
    predicate_norm: str
    value: str
    value_norm: str
    value_entity_id: uuid.UUID | None
    holds: bool
    immutable: bool
    scope: FactScope
    valid_from_event_id: uuid.UUID | None


@dataclass(frozen=True)
class KnowledgeRow:
    id: uuid.UUID
    chapter_id: uuid.UUID
    knower_entity_id: uuid.UUID
    kind: KnowledgeKind
    fact_key: uuid.UUID
    proposition: Mapping[str, Any]
    known_since_event_id: uuid.UUID | None


# 슬롯 하나가 읽어 주는 행들. 사건 슬롯은 사건과 회상 관계를 함께 낸다.
SlotRows = tuple[EventRow | RelationRow | FactRow | KnowledgeRow, ...]


@dataclass(frozen=True)
class BibleSnapshot:
    """한 시점의 정본. 등록되지 않은 슬롯의 칸은 None 이다(빈 튜플은 "슬롯은 있고 행이 없다"). `new_ids` 는 검사 중인 확정이
    새로 넣을 항목 id 들이다(시점 질의에서는 비어 있다)."""

    events: tuple[EventRow, ...] | None
    relations: tuple[RelationRow, ...] | None
    facts: tuple[FactRow, ...] | None
    knowledge: tuple[KnowledgeRow, ...] | None
    new_ids: frozenset[uuid.UUID] = frozenset()


class FindingDraft(_Frozen):
    """규칙 하나가 낸 검사 결과. `item_ids` 는 관련 항목들이고, `payload` 에는 위치·근거 위치만 두고 인용 글은 넣지 않는다."""

    severity: FindingSeverity
    rule: FindingRule
    item_ids: tuple[uuid.UUID, ...]
    payload: dict[str, Any] = {}
