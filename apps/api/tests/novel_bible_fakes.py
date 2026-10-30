"""정본 기억 코어 테스트가 주입하는 가짜 슬롯·원작·어댑터·규칙과 합성 화 만들기.

실제 슬롯은 아직 없으므로 코어는 이 가짜들로만 돈다. 가짜 슬롯은 실제 항목 표(사건·사실·지식)에 쓰고 읽어서, 연결·만료·시점
질의가 실제 표 위에서 검증된다. 가짜 슬롯은 모델 출력이 아니라 원고의 합성 문법으로 항목을 만든다 — 가짜 어댑터는 호출
횟수와 실패만 흉내 낸다(코어가 무엇을 언제 부르고 무엇을 다시 쓰는지가 시험 대상이다).

합성 원고는 문단마다 한 줄이다.

- `사건: 요지` — 사건 하나. 다음 사건 문단 전까지의 문단을 덮는다.
- `사실: 주어|종류|속성(없으면 -)|값|참 또는 거짓` — 사실 하나. 앵커와 근거는 그 문단이다.
- `앎: 아는 이|knows 또는 believes|주어|종류|속성(없으면 -)|값` — 지식 하나.
"""

import uuid
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, TypeVar

from pydantic import BaseModel, ConfigDict
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from api.db.models import Novel, NovelBatch, NovelChapter, NovelChapterRevision, NovelPublication, User
from api.db.models.novel import NovelRevisionSource
from api.db.models.novel_bible import NovelBibleCommit, NovelBibleJob, NovelBibleRevision
from api.db.models.novel_bible_events import NovelBibleEvent, NovelBibleEventRelation
from api.db.models.novel_bible_facts import NovelBibleFact
from api.db.models.novel_bible_knowledge import NovelBibleKnowledge
from api.db.models.prompt import PromptSection
from api.novel_bible.core.contracts import (
    AdapterCallError,
    AdapterCapabilities,
    BibleModelAdapter,
    CoreReadView,
    PromptSource,
    Registry,
    Slot,
)
from api.novel_bible.core.keys import normalize_name, predicate_norm
from api.novel_bible.core.pipeline import run_until_idle
from api.novel_bible.core.queries import current_items
from api.novel_bible.core.quotes import verify_quote
from api.novel_bible.core.types import (
    BibleSnapshot,
    CommitRef,
    EntityName,
    EventRow,
    FactRow,
    FindingDraft,
    ItemDraft,
    KnowledgeRow,
    LinkedItem,
    Manuscript,
    Proposal,
    Proposition,
    QuoteOut,
    RelationRow,
    RenderedPrompt,
    RevisionRef,
    SlotRows,
    SourceCanon,
    SourceCanonRef,
)
from api.novel_bible.ids import FindingRule, FindingSeverity, ItemTable, OperationKey, SlotId
from api.novelize.blocks import build_revision, fresh_ids
from api.novelize.deletion import delete_novels
from factories import _make_user

T = TypeVar("T", bound=BaseModel)
SessionFactory = async_sessionmaker[AsyncSession]

# 대상이 개체인 사실 종류 — 값을 개체로 잇는다.
_ENTITY_VALUED: frozenset[str] = frozenset({"possession", "ability", "relation"})


class FakeOutput(BaseModel):
    items: list[dict[str, Any]] = []


class FakeInput(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    manuscript: Manuscript
    known: list[str]
    source: str


def _proposition(subject: str, kind: str, attribute: str, value: str, holds: bool) -> Proposition:
    return Proposition.model_validate(
        {"subject": subject, "kind": kind, "attribute": None if attribute == "-" else attribute, "value": value,
         "holds": holds}
    )


def _value_names(kind: str, value: str) -> tuple[EntityName, ...]:
    if kind not in _ENTITY_VALUED:
        return ()
    entity_kind = "ability" if kind == "ability" else "character" if kind == "relation" else "object"
    return (EntityName.model_validate({"kind": entity_kind, "name": value}),)


@dataclass
class FakeSlot:
    """사건·사실·지식 가짜 슬롯 하나(어느 것인지는 `id`). `before_apply` 는 커밋 트랜잭션 안에서 항목을 쓰기 직전에 불린다 —
    테스트가 거기서 멈추거나(경합) 예외를 낸다."""

    id: SlotId
    operation: OperationKey
    channel: str
    tables: frozenset[ItemTable]
    output_schema: type[BaseModel] = FakeOutput
    hint_values: frozenset[str] = frozenset({"known_entities"})
    before_apply: Callable[[], Awaitable[None]] | None = None

    async def build_input(self, session: AsyncSession, view: CoreReadView) -> BaseModel:
        canon = await view.source_canon()
        known = await view.known_entities()
        return FakeInput(
            manuscript=await view.manuscript(),
            known=sorted(name.name for name in known),
            source=canon.work_setting if canon is not None else "",
        )

    def prompt_values(self, slot_input: BaseModel) -> dict[str, str]:
        assert isinstance(slot_input, FakeInput)
        lines = "\n".join(f"[{block.index}] {block.text}" for block in slot_input.manuscript.blocks)
        return {"manuscript": lines, "known_entities": ", ".join(slot_input.known), "source": slot_input.source}

    def validate(self, slot_input: BaseModel, output: BaseModel) -> Proposal:
        assert isinstance(slot_input, FakeInput)
        manuscript = slot_input.manuscript
        drafts: list[ItemDraft] = []
        event_starts = [block for block in manuscript.blocks if block.text.startswith("사건:")]
        for number, block in enumerate(manuscript.blocks, start=1):
            quote = verify_quote(manuscript, QuoteOut(paragraph=block.index, text=block.text))
            assert quote is not None
            head, _, rest = block.text.partition(":")
            parts = [part.strip() for part in rest.split("|")]
            if self.id == "events" and head == "사건":
                following = [b for b in event_starts if b.index > block.index]
                end = following[0].index if following else len(manuscript.blocks) + 1
                covers = tuple(b.block_id for b in manuscript.blocks if block.index <= b.index < end)
                drafts.append(
                    ItemDraft(
                        local_key=f"e{number}", table="event", fields={"summary": rest.strip()},
                        quotes=(quote,), covers_blocks=covers,
                    )
                )
            elif self.id == "facts" and head == "사실":
                subject, kind, attribute, value, holds = parts
                drafts.append(
                    ItemDraft(
                        local_key=f"f{number}", table="fact", fields={"scope": "from_here"},
                        names={"subject": (EntityName(kind="character", name=subject),),
                               "value": _value_names(kind, value)},
                        quotes=(quote,), anchor_block=block.block_id,
                        proposition=_proposition(subject, kind, attribute, value, holds == "참"),
                    )
                )
            elif self.id == "knowledge" and head == "앎":
                knower, knowledge_kind, subject, kind, attribute, value = parts
                drafts.append(
                    ItemDraft(
                        local_key=f"k{number}", table="knowledge", fields={"kind": knowledge_kind},
                        names={"knower": (EntityName(kind="character", name=knower),),
                               "subject": (EntityName(kind="character", name=subject),)},
                        quotes=(quote,), anchor_block=block.block_id,
                        proposition=_proposition(subject, kind, attribute, value, True),
                    )
                )
        return Proposal(items=tuple(drafts), dropped={})

    def _orm_rows(self, items: Sequence[LinkedItem], commit: CommitRef, at: RevisionRef) -> list[Any]:
        assert at.id is not None
        common = {"novel_id": commit.novel_id, "chapter_id": commit.chapter_id, "created_revision_id": at.id}
        rows: list[Any] = []
        events = [item for item in items if item.draft.table == "event"]
        for ordinal, item in enumerate(events, start=1):
            rows.append(
                NovelBibleEvent(
                    id=item.id, ordinal=ordinal, actuality="present", summary=item.draft.fields["summary"],
                    anchor_block_ids=list(item.draft.covers_blocks), **common,
                )
            )
        for item in items:
            proposition = item.draft.proposition
            if item.draft.table == "fact":
                assert proposition is not None and item.fact_key is not None
                value_ids = item.entity_ids.get("value", ())
                rows.append(
                    NovelBibleFact(
                        id=item.id, supersedes_id=item.supersedes_id, fact_key=item.fact_key,
                        subject_entity_id=item.entity_ids["subject"][0], kind=proposition.kind,
                        predicate_norm=predicate_norm(proposition.kind, proposition.attribute),
                        value=proposition.value, value_norm=normalize_name(proposition.value),
                        value_entity_id=value_ids[0] if value_ids else None, holds=proposition.holds,
                        immutable=False, onset=False, scope=item.draft.fields["scope"],
                        valid_from_event_id=item.event_id, **common,
                    )
                )
            elif item.draft.table == "knowledge":
                assert proposition is not None and item.fact_key is not None
                rows.append(
                    NovelBibleKnowledge(
                        id=item.id, supersedes_id=item.supersedes_id, knower_entity_id=item.entity_ids["knower"][0],
                        kind=item.draft.fields["kind"], fact_key=item.fact_key,
                        proposition=proposition.model_dump(mode="json"), known_since_event_id=item.event_id,
                        **common,
                    )
                )
        return rows

    async def apply(
        self, session: AsyncSession, items: Sequence[LinkedItem], commit: CommitRef, at: RevisionRef
    ) -> None:
        if self.before_apply is not None:
            await self.before_apply()
        events = [row for row in self._orm_rows(items, commit, at) if isinstance(row, NovelBibleEvent)]
        session.add_all(events)
        await session.flush()
        session.add_all([row for row in self._orm_rows(items, commit, at) if not isinstance(row, NovelBibleEvent)])
        await session.flush()

    def rows(self, items: Sequence[LinkedItem], commit: CommitRef) -> SlotRows:
        provisional = RevisionRef(id=uuid.uuid4(), revision_no=0)
        return tuple(_to_row(row, commit.chapter_ordinal) for row in self._orm_rows(items, commit, provisional))

    async def current_item_ids(
        self, session: AsyncSession, novel_id: uuid.UUID, chapter_id: uuid.UUID, at: RevisionRef
    ) -> list[tuple[ItemTable, uuid.UUID]]:
        found: list[tuple[ItemTable, uuid.UUID]] = []
        for table, model in _MODELS.items():
            if table not in self.tables:
                continue
            statement = current_items(model, table, novel_id, at).where(model.chapter_id == chapter_id)
            found += [(table, row.id) for row in (await session.scalars(statement)).all()]
        return found

    async def read(self, session: AsyncSession, novel_id: uuid.UUID, at: RevisionRef) -> SlotRows:
        rows: list[EventRow | RelationRow | FactRow | KnowledgeRow] = []
        for table, model in _MODELS.items():
            if table not in self.tables:
                continue
            statement = current_items(model, table, novel_id, at).add_columns(NovelChapter.ordinal).join(
                NovelChapter, NovelChapter.id == model.chapter_id
            )
            rows += [_to_row(row, ordinal) for row, ordinal in (await session.execute(statement)).all()]
        return tuple(rows)


_MODELS: dict[ItemTable, Any] = {
    "event": NovelBibleEvent,
    "event_relation": NovelBibleEventRelation,
    "fact": NovelBibleFact,
    "knowledge": NovelBibleKnowledge,
}


def _to_row(row: Any, chapter_ordinal: int) -> EventRow | RelationRow | FactRow | KnowledgeRow:
    if isinstance(row, NovelBibleEvent):
        return EventRow(
            id=row.id, chapter_id=row.chapter_id, chapter_ordinal=chapter_ordinal, ordinal=row.ordinal,
            actuality=row.actuality, anchor_block_ids=tuple(row.anchor_block_ids),
        )
    if isinstance(row, NovelBibleEventRelation):
        return RelationRow(
            id=row.id, chapter_id=row.chapter_id, from_event_id=row.from_event_id, relation=row.relation,
            to_anchor_block_id=row.to_anchor_block_id, to_chapter_id=row.to_chapter_id,
        )
    if isinstance(row, NovelBibleFact):
        return FactRow(
            id=row.id, chapter_id=row.chapter_id, fact_key=row.fact_key, subject_entity_id=row.subject_entity_id,
            kind=row.kind, predicate_norm=row.predicate_norm, value=row.value, value_norm=row.value_norm,
            value_entity_id=row.value_entity_id, holds=row.holds, immutable=row.immutable, scope=row.scope,
            valid_from_event_id=row.valid_from_event_id,
        )
    assert isinstance(row, NovelBibleKnowledge)
    return KnowledgeRow(
        id=row.id, chapter_id=row.chapter_id, knower_entity_id=row.knower_entity_id, kind=row.kind,
        fact_key=row.fact_key, proposition=dict(row.proposition), known_since_event_id=row.known_since_event_id,
    )


def events_slot() -> FakeSlot:
    return FakeSlot("events", "events.extract", "fake_bible_events", frozenset({"event", "event_relation"}))


def facts_slot() -> FakeSlot:
    return FakeSlot("facts", "facts.extract", "fake_bible_facts", frozenset({"fact"}))


def knowledge_slot() -> FakeSlot:
    return FakeSlot("knowledge", "knowledge.extract", "fake_bible_knowledge", frozenset({"knowledge"}))


@dataclass
class FakeSource:
    """원작 정본 가짜 — 표가 없고 글은 이 객체의 `note` 다. 노트가 비면 원작이 없는 것이다."""

    note: str = ""
    version_id: uuid.UUID = field(default_factory=uuid.uuid4)
    id: SlotId = "source"

    async def resolve(self, session: AsyncSession, novel_id: uuid.UUID) -> SourceCanonRef | None:
        if not self.note:
            return None
        return SourceCanonRef(content_version_id=self.version_id, input_hash=f"hash:{self.note}")

    async def load(self, session: AsyncSession, novel_id: uuid.UUID, ref: SourceCanonRef) -> SourceCanon:
        return SourceCanon(ref=ref, work_setting=self.note, keyword_notes={})


def fake_registry(*slots: Slot, source: FakeSource | None = None) -> Registry:
    return Registry(extracting={slot.id: slot for slot in slots}, source=source)


def full_registry(source: FakeSource | None = None) -> Registry:
    return fake_registry(events_slot(), facts_slot(), knowledge_slot(), source=source)


def _sections(prompt_set_id: uuid.UUID) -> list[PromptSection]:
    sections: list[PromptSection] = []
    for channel in ("fake_bible_events", "fake_bible_facts", "fake_bible_knowledge"):
        sections.append(
            PromptSection(
                prompt_set_id=prompt_set_id, channel=channel, scope="both", slot="instruction", variant="",
                body="합성 지시문", conditional=False, order=0,
            )
        )
        sections.append(
            PromptSection(
                prompt_set_id=prompt_set_id, channel=channel, scope="both", slot="body", variant="",
                body="{manuscript}\n{known_entities}\n{source}", conditional=False, order=1,
            )
        )
    return sections


@dataclass
class FakeAdapter:
    """어댑터 하나로 모든 연산을 받는다. `failing` 의 연산은 늘 스키마 불일치(재시도 가능)로 실패한다."""

    prompt_set_id: uuid.UUID = field(default_factory=uuid.uuid4)
    failing: set[OperationKey] = field(default_factory=set)
    calls: list[OperationKey] = field(default_factory=list)
    id: str = "fake"
    capabilities: AdapterCapabilities = field(
        default_factory=lambda: AdapterCapabilities(structured=True, with_instruction=True, max_input_chars=100_000)
    )

    async def prompt_source(self, session: AsyncSession) -> PromptSource:
        return PromptSource(prompt_set_id=self.prompt_set_id, sections=_sections(self.prompt_set_id))

    async def structured(
        self, prompt: RenderedPrompt, schema: type[T], *, records: list[dict[str, Any]], stage: OperationKey
    ) -> T:
        self.calls.append(stage)
        records.append({"stage": stage})
        if stage in self.failing:
            raise AdapterCallError("schema_invalid", retryable=True)
        return schema.model_validate({"items": []})

    def resolver(self) -> Callable[[OperationKey], BibleModelAdapter]:
        return lambda operation: self


@dataclass
class FakeRule:
    """`severity` 결과 하나를 `pick` 이 고른 항목들에 낸다. 고를 것이 없으면 결과가 없다."""

    pick: Callable[[BibleSnapshot], tuple[uuid.UUID, ...]]
    severity: FindingSeverity = "block"
    rule: FindingRule = "exit_then_appearance"
    slots: frozenset[SlotId] = frozenset({"facts"})

    def check(self, snapshot: BibleSnapshot) -> list[FindingDraft]:
        items = self.pick(snapshot)
        if not items:
            return []
        return [FindingDraft(severity=self.severity, rule=self.rule, item_ids=items, payload={})]


def savepoint_factory(session: AsyncSession) -> SessionFactory:
    """테스트 트랜잭션 하나 위에서 코어가 여는 세션 — 커밋은 SAVEPOINT 를 확정하고 롤백은 그 SAVEPOINT 만 되돌린다."""
    return async_sessionmaker(bind=session.bind, join_transaction_mode="create_savepoint", expire_on_commit=False)


async def drain(
    factory: SessionFactory, registry: Registry, adapter: FakeAdapter, rules: Sequence[Any] = ()
) -> None:
    """할 일이 없을 때까지 돌린다. 재시도 대기 중인 작업은 대기 시각을 지금으로 당겨 다시 돌린다."""
    for _ in range(20):
        await run_until_idle(factory, registry, list(rules), adapter.resolver())
        async with factory() as session:
            waiting = (
                select(NovelBibleJob.id)
                .join(NovelBibleCommit, NovelBibleCommit.id == NovelBibleJob.commit_id)
                .where(NovelBibleJob.status == "queued", NovelBibleCommit.status.in_(("pending", "extracting")))
            )
            if (await session.scalar(select(func.count()).select_from(waiting.subquery()))) == 0:
                return
            await session.execute(
                update(NovelBibleJob).where(NovelBibleJob.id.in_(waiting)).values(available_at=func.now())
            )
            await session.commit()
    raise AssertionError("작업이 끝나지 않는다")


async def add_chapter(
    db: AsyncSession, novel_id: uuid.UUID, ordinal: int, body: str
) -> tuple[NovelChapter, NovelChapterRevision]:
    """화 하나짜리 묶음 하나와 그 화, 첫 개정(flush). 묶음 번호는 화 번호와 같다 — 묶음 삭제로 화 하나를 지울 수 있다."""
    now = datetime.now(UTC)
    segment: dict[str, Any] = {
        "start_message_id": uuid.uuid4(), "start_message_created_at": now, "end_message_id": uuid.uuid4(),
        "end_message_created_at": now, "assistant_message_count": 1, "source_hash": "0" * 64,
    }
    batch = NovelBatch(novel_id=novel_id, ordinal=ordinal, target_episode_count=1, **segment)
    db.add(batch)
    await db.flush()
    chapter = NovelChapter(novel_id=novel_id, ordinal=ordinal, batch_id=batch.id, episode_index=0, **segment)
    db.add(chapter)
    await db.flush()
    return chapter, await add_revision(db, chapter.id, body)


async def add_revision(
    db: AsyncSession, chapter_id: uuid.UUID, body: str, *, block_ids: Sequence[uuid.UUID] | None = None,
    source: NovelRevisionSource = "manual_edit",
    reverted_from: uuid.UUID | None = None,
) -> NovelChapterRevision:
    number = await db.scalar(
        select(func.coalesce(func.max(NovelChapterRevision.revision_no), 0)).where(
            NovelChapterRevision.chapter_id == chapter_id
        )
    )
    revision = build_revision(
        chapter_id=chapter_id, revision_no=int(number or 0) + 1, body=body, source=source,
        block_ids=list(block_ids) if block_ids is not None else fresh_ids(body),
        reverted_from_revision_id=reverted_from,
    )
    db.add(revision)
    await db.flush()
    return revision


async def plant_revision(db: AsyncSession, novel_id: uuid.UUID, chapter_id: uuid.UUID, revision_id: uuid.UUID) -> (
    NovelBibleRevision
):
    """화 개정 하나를 확정한 것으로 친 확정·리비전 한 쌍(flush). 번호는 지금 머리 다음."""
    commit = NovelBibleCommit(
        novel_id=novel_id, chapter_id=chapter_id, chapter_revision_id=revision_id, content_hash="0" * 64,
        block_ids_hash="0" * 64, status="committed", actor_kind="system",
    )
    db.add(commit)
    await db.flush()
    head = await db.scalar(
        select(func.coalesce(func.max(NovelBibleRevision.revision_no), 0)).where(
            NovelBibleRevision.novel_id == novel_id
        )
    )
    revision = NovelBibleRevision(novel_id=novel_id, revision_no=int(head or 0) + 1, commit_id=commit.id)
    db.add(revision)
    await db.flush()
    return revision


async def publish(db: AsyncSession, novel_id: uuid.UUID, *, review_status: str | None = None) -> None:
    visibility = "withdrawn" if review_status in ("pending", "rejected") else "public"
    db.add(
        NovelPublication(
            novel_id=novel_id, visibility=visibility, title="공개 제목", synopsis="소개", review_status=review_status,
            review_reason="반려 사유" if review_status == "rejected" else None,
        )
    )
    await db.flush()


# 커밋되는 독립 커넥션으로 만든 행을 끝에 골라 지우는 표지.
COMMITTED_DOMAIN = "novel-bible-core.test"


async def make_novel(db: AsyncSession, *, email_domain: str = "example.com") -> Novel:
    """회원 한 명과 그 소설 한 권(flush). 화는 `add_chapter` 로 더한다."""
    user = _make_user(email=f"user-{uuid.uuid4()}@{email_domain}")
    db.add(user)
    await db.flush()
    novel = Novel(
        user_id=user.id, content_id=uuid.uuid4(), content_type="character", content_title="원작",
        character_name="인물",
    )
    db.add(novel)
    await db.flush()
    return novel


async def delete_committed_novels(engine: AsyncEngine) -> None:
    """`COMMITTED_DOMAIN` 회원의 소설과 회원을 지운다(커밋)."""
    async with async_sessionmaker(engine, expire_on_commit=False)() as cleanup:
        user_ids = (
            await cleanup.scalars(select(User.id).where(User.email.like(f"%@{COMMITTED_DOMAIN}")))
        ).all()
        if user_ids:
            novel_ids = (await cleanup.scalars(select(Novel.id).where(Novel.user_id.in_(user_ids)))).all()
            await delete_novels(cleanup, novel_ids, freed_storage_keys=[])
            await cleanup.execute(delete(User).where(User.id.in_(user_ids)))
        await cleanup.commit()
