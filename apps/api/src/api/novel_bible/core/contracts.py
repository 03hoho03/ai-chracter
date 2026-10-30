"""코어가 아는 계약 — 슬롯·원작·모델 어댑터·규칙. 코어는 이 계약만 알고, 실제 구현은 바깥 입구(`entry.py`)가 인자로 넘긴다
(테스트는 같은 자리에 가짜를 넘긴다). 그래서 코어는 슬롯·규칙·어댑터·모델 호출 계층을 import 하지 않는다."""

import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol, TypeVar

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.models.prompt import PromptSection
from api.novel_bible.core.types import (
    BibleSnapshot,
    CommitRef,
    EntityName,
    FindingDraft,
    LinkedItem,
    Manuscript,
    Proposal,
    RenderedPrompt,
    RevisionRef,
    SlotRows,
    SourceCanon,
    SourceCanonRef,
)
from api.novel_bible.ids import FindingRule, ItemTable, JobFailure, OperationKey, SlotId

T = TypeVar("T", bound=BaseModel)


class CoreReadView(Protocol):
    """슬롯이 자기 표 밖에서 읽는 것. 코어가 확정 하나에 묶어 만든다. 선택 입력은 없으면 None 이다."""

    commit: CommitRef

    async def manuscript(self) -> Manuscript: ...
    async def known_entities(self) -> list[EntityName]: ...
    async def source_canon(self) -> SourceCanon | None: ...


class Slot(Protocol):
    """원고를 읽어 자기 표에 항목을 쓰는 슬롯. 다른 슬롯을 모른다 — 다른 슬롯의 결과에 닿는 칸은 근거(블록)나 명제로만 말하고,
    코어의 연결 단계가 그것을 사건 id·사실 키로 푼다."""

    id: SlotId
    operation: OperationKey  # 이 슬롯의 추출에 어댑터를 배정하는 이름
    channel: str  # novel 레인 문안 채널
    output_schema: type[BaseModel]  # 모델 출력 꼴(구조화 호출의 응답 스키마)
    tables: frozenset[ItemTable]  # 이 슬롯이 쓰는 항목 표 — 화를 다시 확정할 때 만료할 표
    # 렌더 값 중 정본 상태에서 오는 힌트(아는 개체·앞 화 사건 따위). 추출 캐시 열쇠에서 뺀다 — 다른 화가 커밋될 때마다 바뀌어,
    # 넣으면 본문이 같은 재확정도 캐시가 맞지 않는다.
    hint_values: frozenset[str]

    async def build_input(self, session: AsyncSession, view: CoreReadView) -> BaseModel: ...
    def prompt_values(self, slot_input: BaseModel) -> dict[str, str]: ...
    def validate(self, slot_input: BaseModel, output: BaseModel) -> Proposal: ...
    async def apply(
        self, session: AsyncSession, items: Sequence[LinkedItem], commit: CommitRef, at: RevisionRef
    ) -> None: ...
    # 커밋 전 검사가 이번 확정의 새 항목을 정본 행과 같은 꼴로 보게 한다(쓰지 않는다).
    def rows(self, items: Sequence[LinkedItem], commit: CommitRef) -> SlotRows: ...
    async def current_item_ids(
        self, session: AsyncSession, novel_id: uuid.UUID, chapter_id: uuid.UUID, at: RevisionRef
    ) -> list[tuple[ItemTable, uuid.UUID]]: ...
    async def read(self, session: AsyncSession, novel_id: uuid.UUID, at: RevisionRef) -> SlotRows: ...


class SourceSlot(Protocol):
    """원작 정본 — 읽기만 한다. 확정 때 버전을 풀어 확정 행에 버전 id·글 해시를 남기고, 작업 때 같은 버전의 글을 다시 읽어
    준다."""

    id: SlotId

    async def resolve(self, session: AsyncSession, novel_id: uuid.UUID) -> SourceCanonRef | None: ...
    async def load(self, session: AsyncSession, ref: SourceCanonRef) -> SourceCanon: ...


@dataclass(frozen=True)
class Registry:
    """확정에 쓰는 슬롯 묶음. 빠진 슬롯은 작업이 없고, 그 슬롯에 기대는 연결 칸은 미정으로 커밋되며, 그 슬롯을 읽는 규칙은
    건너뛴다."""

    extracting: Mapping[SlotId, Slot]
    source: SourceSlot | None

    def ids(self) -> frozenset[SlotId]:
        found: set[SlotId] = set(self.extracting)
        if self.source is not None:
            found.add(self.source.id)
        return frozenset(found)


@dataclass(frozen=True)
class AdapterCapabilities:
    structured: bool
    with_instruction: bool
    max_input_chars: int


@dataclass(frozen=True)
class PromptSource:
    prompt_set_id: uuid.UUID
    sections: Sequence[PromptSection]


class BibleModelAdapter(Protocol):
    """모델 하나와 그 모델이 읽을 문안. 코어는 이 계약만 알고 어느 모델인지 모른다. 문안은 어댑터가 읽는다 — 문안을 고르는
    축이 모델이라, 코어가 읽으면 모델 이름을 알게 된다."""

    id: str
    capabilities: AdapterCapabilities

    async def prompt_source(self, session: AsyncSession) -> PromptSource: ...
    async def structured(
        self, prompt: RenderedPrompt, schema: type[T], *, records: list[dict[str, Any]], stage: OperationKey
    ) -> T: ...


AdapterResolver = Callable[[OperationKey], BibleModelAdapter]


class AdapterCallError(Exception):
    """어댑터가 공급자 예외를 코어가 아는 실패 사유로 바꿔 올린다. 코어는 공급자 예외 타입을 import 하지 않는다."""

    def __init__(self, code: JobFailure, *, retryable: bool) -> None:
        super().__init__(code)
        self.code: JobFailure = code
        self.retryable = retryable


class Rule(Protocol):
    """검사 규칙 하나. 읽는 슬롯(`slots`)이 등록부에 하나라도 없으면 건너뛴다. 결과는 이번 확정의 새 항목이 하나라도 낀
    것만 남는다 — 이미 정본에 있던 충돌이 다른 화 확정을 매번 막지 않게."""

    rule: FindingRule
    slots: frozenset[SlotId]

    def check(self, snapshot: BibleSnapshot) -> Sequence[FindingDraft]: ...
