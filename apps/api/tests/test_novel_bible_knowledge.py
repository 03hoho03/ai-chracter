"""정본 기억 지식 슬롯 — 원고에서 인물이 무엇을 안다(`knows`)거나 믿는다(`believes`)를 뽑아 지식 표에 쓴다.

입력은 확정 개정의 문단(번호만)과 아는 개체뿐이다 — 장면 구성안·원작·채팅 기억은 읽지 않는다. 앎 주체(아는 사람)와 명제의
주어(무엇에 대한 앎인가)는 다른 칸이다. `knows` 의 키는 같은 명제를 낸 사실 행의 키와 같고, 사실 행이 없어도 명제만으로 계산된다.
`believes` 는 사실과 다른 내용이어도 되는 별도 명제다. 그리고 등록부에서 슬롯 하나를 빼도 남은 슬롯의 결과는 같고, 뺀 슬롯에 기대는
연결 칸만 미정으로 커밋된다.

원고·원작 글은 합성 문장이고 모델은 가짜 어댑터다(연산마다 정해 둔 출력을 차례로 돌려준다)."""

import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, TypeVar

import pytest
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.models import (
    Content,
    ContentType,
    ContentVersion,
    ContentVisibility,
    ModerationStatus,
    Novel,
    NovelChapter,
    NovelChapterRevision,
    StoryPromptTemplate,
    StoryVersionDetail,
)
from api.db.models.novel_bible import (
    NovelBibleAdaptationCandidate,
    NovelBibleCommit,
    NovelBibleEntity,
    NovelBibleEvidence,
    NovelBibleExpiration,
    NovelBibleFinding,
    NovelBibleJob,
)
from api.db.models.novel_bible_events import NovelBibleEvent
from api.db.models.novel_bible_facts import NovelBibleFact
from api.db.models.novel_bible_knowledge import NovelBibleKnowledge
from api.db.models.prompt import PromptSection
from api.novel_bible.core.confirm import Actor, confirm
from api.novel_bible.core.contracts import AdapterCapabilities, BibleModelAdapter, PromptSource, Registry, Slot
from api.novel_bible.core.keys import fact_key
from api.novel_bible.core.known import known_entities_text
from api.novel_bible.core.pipeline import run_until_idle
from api.novel_bible.core.queries import knowledge_at, revision_at
from api.novel_bible.core.types import (
    BibleSnapshot,
    CommitRef,
    EntityName,
    KnowledgeRow,
    Manuscript,
    ManuscriptBlock,
    PlayFact,
    RenderedPrompt,
    SceneHint,
    SourceCanon,
)
from api.novel_bible.ids import EntityKind, FactKind, KnowledgeKind, OperationKey, SlotId
from api.novel_bible.registry import REGISTRY
from api.novel_bible.slots.facts.schema import FactsOutput
from api.novel_bible.slots.facts.slot import FactsInput, FactsSlot
from api.novel_bible.slots.knowledge.schema import KnowledgeOutput
from api.novel_bible.slots.knowledge.slot import KnowledgeInput, KnowledgeSlot
from novel_bible_fakes import FakeRule, add_chapter, add_revision, make_novel, savepoint_factory

T = TypeVar("T", bound=BaseModel)
SYSTEM = Actor(kind="system")


# ── 합성 입력 ────────────────────────────────────────────────────────


def _manuscript(*texts: str) -> Manuscript:
    blocks = tuple(
        ManuscriptBlock(index=number, block_id=uuid.uuid4(), text=text) for number, text in enumerate(texts, start=1)
    )
    return Manuscript(revision_id=uuid.uuid4(), blocks=blocks)


def _about(
    subject: str, kind: FactKind, value: str, *, attribute: str | None = None, holds: bool = True,
    subject_kind: EntityKind = "character",
) -> dict[str, Any]:
    return {"subject": subject, "subject_kind": subject_kind, "kind": kind, "attribute": attribute, "value": value,
            "holds": holds}


def _known(knower: str, kind: KnowledgeKind, about: dict[str, Any], quote: tuple[int, str]) -> dict[str, Any]:
    return {"knower": knower, "kind": kind, "about": about, "quote": {"paragraph": quote[0], "text": quote[1]}}


def _fact(about: dict[str, Any], quote: tuple[int, str], *, onset: bool = False,
          source: tuple[str, str] | None = None) -> dict[str, Any]:
    return {**about, "immutable": False, "onset": onset, "scope": "from_here",
            "quote": {"paragraph": quote[0], "text": quote[1]},
            "source_difference": {"label": source[0], "quote": source[1]} if source else None,
            "play_difference": None}


def _output(*items: dict[str, Any]) -> KnowledgeOutput:
    return KnowledgeOutput.model_validate({"items": list(items)})


def _input(manuscript: Manuscript, *, known: list[EntityName] | None = None) -> KnowledgeInput:
    return KnowledgeInput(manuscript=manuscript, known=known or [])


# ── 입력·렌더 값 ─────────────────────────────────────────────────────


@dataclass
class _OnlyManuscriptView:
    """원고와 아는 개체만 내주는 읽기 뷰. 장면 구성안·원작·채팅 기억을 읽으면 실패한다."""

    manuscript_value: Manuscript
    known: list[EntityName]
    commit: CommitRef = field(
        default_factory=lambda: CommitRef(
            commit_id=uuid.uuid4(), novel_id=uuid.uuid4(), chapter_id=uuid.uuid4(), chapter_revision_id=uuid.uuid4(),
            chapter_ordinal=1, scope="character",
        )
    )

    async def manuscript(self) -> Manuscript:
        return self.manuscript_value

    async def known_entities(self) -> list[EntityName]:
        return self.known

    async def scene_hints(self) -> list[SceneHint]:
        raise AssertionError("지식 입력은 장면 구성안을 읽지 않는다")

    async def source_canon(self) -> SourceCanon | None:
        raise AssertionError("지식 입력은 원작을 읽지 않는다")

    async def play_facts(self) -> list[PlayFact] | None:
        raise AssertionError("지식 입력은 채팅 기억을 읽지 않는다")


async def test_the_input_reads_only_the_manuscript_and_the_known_entities(db_session: AsyncSession) -> None:
    """깨지는 시나리오: 장면 구성안을 읽으면 계획에만 있는 앎이 정본이 되고, 채팅 기억을 읽으면 플레이에서만 그랬던 앎이 원고
    근거 없이 들어온다."""
    manuscript = _manuscript("합성 문단이다.")
    known = [EntityName(kind="character", name="하나")]

    slot_input = await KnowledgeSlot().build_input(db_session, _OnlyManuscriptView(manuscript, known))

    assert slot_input == KnowledgeInput(manuscript=manuscript, known=known)


def test_the_prompt_values_number_paragraphs_and_share_the_known_entities_line() -> None:
    """원고는 장면 표시 없이 `[번호] 글`, 아는 개체는 다른 슬롯과 같은 코어 글이다. 아는 개체만 힌트라 추출 캐시 열쇠에서
    빠진다. 깨지는 시나리오: 꼴이 바뀌면 같은 꼴을 설명하는 지시문과 어긋나 모델이 문단 번호를 틀리게 낸다."""
    known = [EntityName(kind="object", name="열쇠"), EntityName(kind="character", name="하나", aliases=("큰언니",))]
    slot_input = _input(_manuscript("첫째 문단이다.", "둘째 문단이다."), known=known)

    values = KnowledgeSlot().prompt_values(slot_input)

    assert values == {"manuscript": "[1] 첫째 문단이다.\n[2] 둘째 문단이다.", "known_entities": known_entities_text(known)}
    assert values["known_entities"] == "- 열쇠 (사물)\n- 하나 (인물) — 별칭: 큰언니"
    assert KnowledgeSlot().hint_values == frozenset({"known_entities"})


# ── 검증 ────────────────────────────────────────────────────────────


def test_validation_drops_bad_items_one_by_one() -> None:
    """명제 칸은 사실과 같은 규칙으로 본다 — 인용 구절이 문단에 없음, 생사 값이 정해진 값이 아님, 값이 빔, 유지가 거짓인데 속성,
    관계 이름이 빔. 버린 항목만 빠지고 나머지는 남는다."""
    manuscript = _manuscript("둘은 하나가 검을 가진 것을 안다.")
    quote = (1, "하나가 검을 가진 것을 안다")
    output = _output(
        _known("둘", "knows", _about("하나", "possession", "검"), (1, "원고에 없는 구절")),
        _known("둘", "knows", _about("하나", "life", "반쯤 살아 있음"), quote),
        _known("둘", "knows", _about("하나", "possession", "  "), quote),
        _known("둘", "knows", _about("하나", "attribute", "크다", attribute="키", holds=False), quote),
        _known("둘", "knows", _about("하나", "relation", "셋", attribute=" "), quote),
        _known("둘", "knows", _about("하나", "possession", "검"), quote),
    )

    proposal = KnowledgeSlot().validate(_input(manuscript), output)

    assert [draft.proposition.value for draft in proposal.items if draft.proposition] == ["검"]
    assert proposal.dropped == {
        "quote_not_found": 1, "value_invalid": 1, "value_empty": 1, "holds_invalid": 1, "attribute_missing": 1,
    }


def test_the_knower_and_the_proposition_subject_are_named_apart() -> None:
    """앎 주체는 늘 인물로 `knower` 에, 명제의 주어는 명제의 주어 종류로 `subject` 에, 소지 대상은 사물로 `value` 에 간다. 앵커는
    인용 블록이다. 깨지는 시나리오: 둘을 한 칸에서 읽으면 "둘이 하나의 검을 안다"가 "하나가 둘의 검을 안다"로 뒤집혀, 아는
    사람이 엉뚱한 인물이 되고 명제 키도 다른 사람의 소지가 된다."""
    manuscript = _manuscript("하나가 검을 받는다.", "둘은 하나가 검을 받은 것을 안다.")
    output = _output(_known("둘", "knows", _about("하나", "possession", " 검 "), (2, "검을 받은 것을 안다")))

    (draft,) = KnowledgeSlot().validate(_input(manuscript), output).items

    assert draft.table == "knowledge"
    assert draft.names == {
        "knower": (EntityName(kind="character", name="둘"),),
        "subject": (EntityName(kind="character", name="하나"),),
        "value": (EntityName(kind="object", name="검"),),
    }
    assert draft.proposition is not None
    assert (draft.proposition.subject, draft.proposition.kind, draft.proposition.value) == ("하나", "possession", "검")
    assert draft.fields == {"kind": "knows"}
    assert draft.anchor_block == manuscript.blocks[1].block_id
    assert draft.quotes[0].block_id == manuscript.blocks[1].block_id


@pytest.mark.parametrize(
    "about",
    [
        pytest.param(_about("하나", "possession", "검"), id="possession"),
        pytest.param(_about("하나", "ability", "불꽃"), id="ability"),
        pytest.param(_about("하나", "relation", "셋", attribute="친구"), id="relation"),
        pytest.param(_about("하나", "possession", "검", holds=False), id="lost-possession"),
        pytest.param(_about("검", "attribute", "무딤", attribute="날", subject_kind="object"), id="thing-attribute"),
        pytest.param(_about("하나", "presence", " Departed "), id="presence"),
    ],
)
def test_knowledge_and_a_fact_of_the_same_proposition_carry_the_same_proposition_and_names(about: dict[str, Any]) -> None:
    """같은 명제면 두 슬롯이 같은 명제 칸과 같은 개체 이름(대상의 개체 종류 포함)을 낸다 — 코어가 이 둘로 안정 키를 만든다.
    깨지는 시나리오: 한쪽이 능력 대상을 사물로 잇거나 값을 다르게 다듬으면, 같은 앎과 사실의 키가 갈려 앎이 사실에 이어지지
    않는다."""
    manuscript = _manuscript("둘은 그 일을 안다.")
    quote = (1, "그 일을 안다")

    (known,) = KnowledgeSlot().validate(_input(manuscript), _output(_known("둘", "knows", about, quote))).items
    facts_input = FactsInput(manuscript=manuscript, known=[], known_attributes=[], source=None, play=None)
    (fact,) = FactsSlot().validate(facts_input, FactsOutput.model_validate({"facts": [_fact(about, quote)]})).items

    assert known.proposition == fact.proposition
    assert {name: known.names[name] for name in ("subject", "value") if name in known.names} == fact.names


def test_a_belief_is_its_own_proposition_and_may_differ_from_the_facts() -> None:
    """믿음은 사실 행에 붙인 앎이 아니라 명제 하나다 — 원고의 사실과 다른 내용(거짓 믿음)도 그대로 싣는다."""
    manuscript = _manuscript("하나는 살아 있다.", "셋은 하나가 죽었다고 믿는다.")
    output = _output(_known("셋", "believes", _about("하나", "life", "dead"), (2, "죽었다고 믿는다")))

    (draft,) = KnowledgeSlot().validate(_input(manuscript), output).items

    assert draft.fields == {"kind": "believes"}
    assert draft.proposition is not None and (draft.proposition.kind, draft.proposition.value) == ("life", "dead")


# ── 확정 한 바퀴 ─────────────────────────────────────────────────────

_SLOTS: dict[str, list[tuple[str, str, bool]]] = {
    "novel_bible_events": [("instruction", "합성 지시문", False), ("manuscript", "{manuscript}", False),
                           ("scene_hints", "{scene_hints}", True), ("known_entities", "{known_entities}", True),
                           ("prior_events", "{prior_events}", True)],
    "novel_bible_facts": [("instruction", "합성 지시문", False), ("manuscript", "{manuscript}", False),
                          ("known_entities", "{known_entities}", True),
                          ("known_attributes", "{known_attributes}", True),
                          ("source_canon", "{source_canon}", True), ("play_facts", "{play_facts}", True)],
    "novel_bible_knowledge": [("instruction", "합성 지시문", False), ("manuscript", "원고\n{manuscript}", False),
                              ("known_entities", "아는 개체\n{known_entities}", True)],
}


def _sections(prompt_set_id: uuid.UUID) -> list[PromptSection]:
    return [
        PromptSection(prompt_set_id=prompt_set_id, channel=channel, scope="both", slot=slot, variant="", body=body,
                      conditional=conditional, order=order)
        for channel, slots in _SLOTS.items()
        for order, (slot, body, conditional) in enumerate(slots)
    ]


@dataclass
class ScriptedAdapter:
    """연산마다 정해 둔 출력을 호출마다 차례로 돌려주고, 받은 문안을 연산마다 남긴다."""

    outputs: dict[OperationKey, list[dict[str, Any]]]
    prompts: dict[OperationKey, list[RenderedPrompt]] = field(default_factory=dict)
    prompt_set_id: uuid.UUID = field(default_factory=uuid.uuid4)
    id: str = "scripted"
    capabilities: AdapterCapabilities = field(
        default_factory=lambda: AdapterCapabilities(structured=True, with_instruction=True, max_input_chars=100_000)
    )

    async def prompt_source(self, session: AsyncSession) -> PromptSource:
        return PromptSource(prompt_set_id=self.prompt_set_id, sections=_sections(self.prompt_set_id))

    async def structured(
        self, prompt: RenderedPrompt, schema: type[T], *, records: list[dict[str, Any]], stage: OperationKey
    ) -> T:
        self.prompts.setdefault(stage, []).append(prompt)
        return schema.model_validate(self.outputs[stage].pop(0))

    def resolver(self) -> Callable[[OperationKey], BibleModelAdapter]:
        return lambda operation: self


def _registry(*slot_ids: SlotId) -> Registry:
    """실제 등록부의 부분집합."""
    extracting: dict[SlotId, Slot] = {slot_id: slot for slot_id, slot in REGISTRY.extracting.items() if slot_id in slot_ids}
    return Registry(extracting=extracting, source=REGISTRY.source if "source" in slot_ids else None)


async def _confirm_and_run(
    db: AsyncSession, chapter: NovelChapter, revision: NovelChapterRevision, adapter: ScriptedAdapter,
    registry: Registry, rules: list[Any] | None = None,
) -> uuid.UUID:
    result = await confirm(
        db, registry, novel_id=chapter.novel_id, chapter_id=chapter.id, revision_id=revision.id, actor=SYSTEM
    )
    await run_until_idle(savepoint_factory(db), registry, rules or [], adapter.resolver())
    return result.commit_id


async def _status(db: AsyncSession, commit_id: uuid.UUID) -> str | None:
    status: str | None = await db.scalar(select(NovelBibleCommit.status).where(NovelBibleCommit.id == commit_id))
    return status


async def _entity(db: AsyncSession, novel_id: uuid.UUID, kind: str, name: str) -> uuid.UUID:
    entity_id = await db.scalar(
        select(NovelBibleEntity.id).where(
            NovelBibleEntity.novel_id == novel_id, NovelBibleEntity.kind == kind, NovelBibleEntity.name_norm == name
        )
    )
    assert entity_id is not None
    return entity_id


async def _knowledge(db: AsyncSession, chapter_id: uuid.UUID) -> list[NovelBibleKnowledge]:
    statement = select(NovelBibleKnowledge).where(NovelBibleKnowledge.chapter_id == chapter_id)
    return list((await db.scalars(statement.order_by(NovelBibleKnowledge.kind))).all())


async def _events(db: AsyncSession, chapter_id: uuid.UUID) -> list[NovelBibleEvent]:
    statement = select(NovelBibleEvent).where(NovelBibleEvent.chapter_id == chapter_id)
    return list((await db.scalars(statement.order_by(NovelBibleEvent.ordinal))).all())


def _event(key: str, paragraphs: list[int], quote: tuple[int, str], present: list[str], *,
           actuality: str = "present") -> dict[str, Any]:
    return {
        "key": key, "summary": "합성 요지", "paragraphs": paragraphs, "actuality": actuality, "present": present,
        "mentioned": [], "uses": [], "quote": {"paragraph": quote[0], "text": quote[1]},
    }


BODY = "하나가 검을 받는다.\n\n둘은 하나가 검을 받은 것을 안다.\n\n셋은 하나가 죽었다고 믿는다."


def _events_output() -> dict[str, Any]:
    return {"events": [_event("e1", [1], (1, "검을 받는다"), ["하나"]),
                       _event("e2", [2, 3], (2, "검을 받은 것을 안다"), ["둘", "셋"])], "relations": []}


def _facts_output() -> dict[str, Any]:
    return {"facts": [_fact(_about("하나", "possession", "검"), (1, "검을 받는다"), onset=True)]}


def _knowledge_output() -> dict[str, Any]:
    return {"items": [
        _known("둘", "knows", _about("하나", "possession", "검"), (2, "검을 받은 것을 안다")),
        _known("셋", "believes", _about("하나", "life", "dead"), (3, "죽었다고 믿는다")),
    ]}


def _proposition_key(proposition: dict[str, Any]) -> uuid.UUID:
    """저장된 명제 칸만으로 안정 키를 다시 계산한다."""
    token = proposition["value_entity_id"] or proposition["value_norm"]
    return fact_key(
        uuid.UUID(proposition["subject_entity_id"]), proposition["kind"], proposition["predicate_norm"], token,
        proposition["holds"],
    )


async def test_a_confirmed_chapter_commits_knowledge_with_its_knower_key_and_event(
    db_session: AsyncSession,
) -> None:
    """`knows` 는 같은 명제의 사실 행과 같은 키, `believes` 는 사실과 다른 명제의 키를 받는다. 앎 주체는 아는 인물이고 명제의
    주어는 따로 저장된다. 알게 된 사건은 인용 블록을 덮는 이번 확정의 사건이다. 깨지는 시나리오: 앎 주체와 주어를 바꿔 쓰면 아는
    사람이 엉뚱한 인물이 되고, 저장된 명제 칸으로 키를 다시 만들 수 없으면 사실이 대체된 뒤 앎을 다시 이을 길이 없다."""
    novel = await make_novel(db_session)
    chapter, revision = await add_chapter(db_session, novel.id, 1, BODY)
    adapter = ScriptedAdapter({"events.extract": [_events_output()], "facts.extract": [_facts_output()],
                               "knowledge.extract": [_knowledge_output()]})

    commit_id = await _confirm_and_run(
        db_session, chapter, revision, adapter, _registry("events", "facts", "knowledge")
    )

    assert await _status(db_session, commit_id) == "committed"
    believes, knows = await _knowledge(db_session, chapter.id)
    first, second = await _events(db_session, chapter.id)
    (fact,) = (await db_session.scalars(select(NovelBibleFact).where(NovelBibleFact.chapter_id == chapter.id))).all()
    one, two, three = [await _entity(db_session, novel.id, "character", name) for name in ("하나", "둘", "셋")]
    sword = await _entity(db_session, novel.id, "object", "검")
    assert (knows.knower_entity_id, knows.kind, knows.known_since_event_id) == (two, "knows", second.id)
    assert knows.fact_key == fact.fact_key == fact_key(one, "possession", "possession", str(sword), True)
    assert knows.proposition == {
        "subject_entity_id": str(one), "kind": "possession", "predicate_norm": "possession", "value": "검",
        "value_norm": "검", "value_entity_id": str(sword), "holds": True,
    }
    assert _proposition_key(knows.proposition) == knows.fact_key
    assert (believes.knower_entity_id, believes.kind, believes.known_since_event_id) == (three, "believes", second.id)
    assert believes.fact_key == fact_key(one, "life", "life", "dead", True) == _proposition_key(believes.proposition)
    assert believes.proposition["value_entity_id"] is None
    assert {row.status for row in (knows, believes)} == {"confirmed"}
    assert first.id != second.id
    evidence = (
        await db_session.execute(
            select(NovelBibleEvidence.item_id, NovelBibleEvidence.block_id).where(
                NovelBibleEvidence.item_table == "knowledge"
            )
        )
    ).all()
    assert set(evidence) == {(knows.id, revision.block_ids[1]), (believes.id, revision.block_ids[2])}
    prompt = adapter.prompts["knowledge.extract"][0].prompt
    assert "원고\n[1] 하나가 검을 받는다.\n[2] 둘은" in prompt and "아는 개체" not in prompt


@pytest.mark.parametrize(
    ("about", "target"),
    [
        pytest.param(_about("하나", "possession", "검"), ("object", "검"), id="possession"),
        pytest.param(_about("하나", "ability", "불꽃"), ("ability", "불꽃"), id="ability"),
        pytest.param(_about("하나", "relation", "셋", attribute="친구"), ("character", "셋"), id="relation"),
    ],
)
async def test_knowledge_of_a_possession_an_ability_or_a_relation_gets_the_key_of_the_same_fact(
    db_session: AsyncSession, about: dict[str, Any], target: tuple[str, str]
) -> None:
    """대상이 개체인 명제는 대상 개체 id 가 키에 든다. 같은 명제를 낸 사실과 앎이 같은 대상 개체로 이어져 같은 키를 받는다.
    깨지는 시나리오: 지식 쪽이 대상 이름을 싣지 않거나 다른 종류의 개체로 이으면 키가 갈려 앎이 그 사실에 닿지 않는다."""
    novel = await make_novel(db_session)
    chapter, revision = await add_chapter(db_session, novel.id, 1, "하나에 대한 합성 문단.\n\n둘은 그 일을 안다.")
    adapter = ScriptedAdapter({
        "facts.extract": [{"facts": [_fact(about, (1, "하나에 대한 합성 문단"))]}],
        "knowledge.extract": [{"items": [_known("둘", "knows", about, (2, "그 일을 안다"))]}],
    })

    commit_id = await _confirm_and_run(db_session, chapter, revision, adapter, _registry("facts", "knowledge"))

    assert await _status(db_session, commit_id) == "committed"
    (fact,) = (await db_session.scalars(select(NovelBibleFact).where(NovelBibleFact.chapter_id == chapter.id))).all()
    (known,) = await _knowledge(db_session, chapter.id)
    target_id = await _entity(db_session, novel.id, *target)
    assert fact.value_entity_id == target_id
    assert known.proposition["value_entity_id"] == str(target_id)
    assert known.fact_key == fact.fact_key


async def test_knowledge_anchored_in_a_dream_is_stored_and_its_event_keeps_the_dream(db_session: AsyncSession) -> None:
    """꿈·상상 장면에서 생긴 앎도 저장되고, 알게 된 사건이 그 꿈 사건이라 현실성은 사건에서 읽힌다. 깨지는 시나리오: 꿈 장면의
    앎을 버리거나 다른 사건에 이으면, 꿈 속에서 알게 된 것을 현실에서 안 것으로 읽어 막을 수 있는 정보가 사라진다."""
    novel = await make_novel(db_session)
    chapter, revision = await add_chapter(db_session, novel.id, 1, "둘이 잠든다.\n\n꿈속에서 둘은 하나가 검을 가졌다는 걸 안다.")
    adapter = ScriptedAdapter({
        "events.extract": [{"events": [_event("e1", [1], (1, "둘이 잠든다"), ["둘"]),
                                       _event("e2", [2], (2, "꿈속에서"), ["둘"], actuality="dream_or_imagined")],
                            "relations": []}],
        "knowledge.extract": [{"items": [
            _known("둘", "knows", _about("하나", "possession", "검"), (2, "검을 가졌다는 걸 안다"))
        ]}],
    })

    commit_id = await _confirm_and_run(db_session, chapter, revision, adapter, _registry("events", "knowledge"))

    assert await _status(db_session, commit_id) == "committed"
    (known,) = await _knowledge(db_session, chapter.id)
    _, dream = await _events(db_session, chapter.id)
    assert known.known_since_event_id == dream.id
    assert dream.actuality == "dream_or_imagined"


async def test_reconfirming_expires_the_chapters_knowledge_and_new_rows_supersede_the_same_knower_kind_and_key(
    db_session: AsyncSession,
) -> None:
    novel = await make_novel(db_session)
    chapter, revision = await add_chapter(db_session, novel.id, 1, BODY)
    adapter = ScriptedAdapter({"knowledge.extract": [_knowledge_output(), _knowledge_output()]})
    await _confirm_and_run(db_session, chapter, revision, adapter, _registry("knowledge"))
    old = {(row.knower_entity_id, row.kind, row.fact_key): row.id for row in await _knowledge(db_session, chapter.id)}
    replacement = await add_revision(db_session, chapter.id, BODY + "\n\n셋이 떠난다.")

    commit_id = await _confirm_and_run(db_session, chapter, replacement, adapter, _registry("knowledge"))

    assert await _status(db_session, commit_id) == "committed"
    head = await revision_at(db_session, novel.id, None)
    expired = (
        await db_session.execute(
            select(NovelBibleExpiration.item_table, NovelBibleExpiration.item_id).where(
                NovelBibleExpiration.revision_id == head.id
            )
        )
    ).all()
    assert set(expired) == {("knowledge", item_id) for item_id in old.values()}
    new_rows = [row for row in await _knowledge(db_session, chapter.id) if row.id not in old.values()]
    assert {old[row.knower_entity_id, row.kind, row.fact_key]: row.supersedes_id for row in new_rows} == {
        item_id: item_id for item_id in old.values()
    }
    current = await KnowledgeSlot().read(db_session, novel.id, head)
    assert all(isinstance(row, KnowledgeRow) for row in current)
    assert {row.id for row in current} == {row.id for row in new_rows}
    assert {item for _, item in await KnowledgeSlot().current_item_ids(db_session, novel.id, chapter.id, head)} == {
        row.id for row in new_rows
    }
    before = await KnowledgeSlot().read(db_session, novel.id, await revision_at(db_session, novel.id, head.revision_no - 1))
    assert {row.id for row in before} == set(old.values())


# ── 시점 질의 ───────────────────────────────────────────────────────

FIRST = "하나가 쓰러져 죽는다."
SECOND = "둘은 하나가 죽은 것을 안다.\n\n둘은 하나가 살아 있다고 믿는다."


def _second_outputs() -> dict[OperationKey, list[dict[str, Any]]]:
    return {
        "events.extract": [{"events": [_event("e1", [1, 2], (1, "죽은 것을 안다"), ["둘"])], "relations": []}],
        "facts.extract": [{"facts": []}],
        "knowledge.extract": [{"items": [
            _known("둘", "knows", _about("하나", "life", "dead"), (1, "죽은 것을 안다")),
            _known("둘", "believes", _about("하나", "life", "alive"), (2, "살아 있다고 믿는다")),
        ]}],
    }


def _first_outputs() -> dict[OperationKey, list[dict[str, Any]]]:
    return {
        "events.extract": [{"events": [_event("e1", [1], (1, "쓰러져 죽는다"), ["하나"])], "relations": []}],
        "facts.extract": [{"facts": [_fact(_about("하나", "life", "dead"), (1, "쓰러져 죽는다"), onset=True)]}],
        "knowledge.extract": [{"items": []}],
    }


async def test_knowledge_at_pairs_a_known_fact_keeps_a_belief_apart_and_follows_a_reconfirmed_fact(
    db_session: AsyncSession,
) -> None:
    """2화의 앎은 1화의 같은 명제 사실 행과 짝이 되고, 믿음은 사실과 따로 명제 그대로 나온다. 1화를 다시 확정해 사실이 새 행이
    되면 2화 앎은 행을 고치지 않아도 새 사실 행과 짝이 된다."""
    novel = await make_novel(db_session)
    first, first_revision = await add_chapter(db_session, novel.id, 1, FIRST)
    second, second_revision = await add_chapter(db_session, novel.id, 2, SECOND)
    registry = _registry("events", "facts", "knowledge")
    await _confirm_and_run(db_session, first, first_revision, ScriptedAdapter(_first_outputs()), registry)
    await _confirm_and_run(db_session, second, second_revision, ScriptedAdapter(_second_outputs()), registry)
    two = await _entity(db_session, novel.id, "character", "둘")
    (event,) = await _events(db_session, second.id)

    at = await knowledge_at(db_session, novel.id, registry, knower_entity_id=two, event_id=event.id)

    old_fact = await db_session.scalar(select(NovelBibleFact.id).where(NovelBibleFact.chapter_id == first.id))
    ((known, paired),) = at.knows
    (belief,) = at.believes
    assert paired is not None and paired.id == old_fact
    assert known.kind == "knows" and known.fact_key == paired.fact_key
    assert belief.proposition["value_norm"] == "alive" and belief.fact_key != paired.fact_key
    assert at.undetermined == ()

    replacement = await add_revision(db_session, first.id, FIRST + "\n\n바람이 분다.")
    await _confirm_and_run(db_session, first, replacement, ScriptedAdapter(_first_outputs()), registry)
    again = await knowledge_at(db_session, novel.id, registry, knower_entity_id=two, event_id=event.id)

    ((_, renewed),) = again.knows
    assert renewed is not None and renewed.id != old_fact and renewed.fact_key == paired.fact_key


async def test_knowledge_committed_without_the_facts_slot_reads_as_fact_undetermined(db_session: AsyncSession) -> None:
    novel = await make_novel(db_session)
    chapter, revision = await add_chapter(db_session, novel.id, 1, SECOND)
    outputs = _second_outputs()
    registry = _registry("events", "knowledge")
    await _confirm_and_run(db_session, chapter, revision, ScriptedAdapter(outputs), registry)
    one, two = [await _entity(db_session, novel.id, "character", name) for name in ("하나", "둘")]
    (event,) = await _events(db_session, chapter.id)

    at = await knowledge_at(db_session, novel.id, registry, knower_entity_id=two, event_id=event.id)

    ((known, paired),) = at.knows
    assert paired is None
    assert known.fact_key == fact_key(one, "life", "life", "dead", True)


# ── 슬롯 독립 ───────────────────────────────────────────────────────

_SETTING = "합성 작품 설정 — 하나는 처음부터 활을 지닌다."
_INDEPENDENCE_BODY = (
    "하나가 검을 받는다.\n\n둘은 하나가 검을 받은 것을 안다.\n\n셋은 하나가 죽었다고 믿는다.\n\n하나는 숲으로 떠난다."
)


def _independence_outputs() -> dict[OperationKey, list[dict[str, Any]]]:
    return {
        "events.extract": [{"events": [_event("e1", [1, 2], (1, "검을 받는다"), ["하나", "둘"]),
                                       _event("e2", [3, 4], (4, "숲으로 떠난다"), ["하나", "셋"])], "relations": []}],
        "facts.extract": [{"facts": [
            _fact(_about("하나", "possession", "검"), (1, "검을 받는다"), onset=True,
                  source=("S", "하나는 처음부터 활을 지닌다")),
            _fact(_about("하나", "presence", "departed"), (4, "숲으로 떠난다"), onset=True),
        ]}],
        "knowledge.extract": [{"items": [
            _known("둘", "knows", _about("하나", "possession", "검"), (2, "검을 받은 것을 안다")),
            _known("셋", "believes", _about("하나", "life", "dead"), (3, "죽었다고 믿는다")),
        ]}],
    }


async def _story_novel(db: AsyncSession) -> Novel:
    """방 없이 남은 스토리 원작의 소설 — 원작 버전은 지금 발행본이고 작품 설정 글이 있다."""
    novel = await make_novel(db)
    content = Content(
        creator_user_id=novel.user_id, type=ContentType.STORY, hashtags=[], visibility=ContentVisibility.PUBLIC,
        moderation_status=ModerationStatus.NORMAL,
    )
    db.add(content)
    await db.flush()
    version = ContentVersion(
        content_id=content.id, version_number=1, published_at=datetime.now(UTC), detail_description="설명"
    )
    db.add(version)
    await db.flush()
    db.add(StoryVersionDetail(content_version_id=version.id, name="스토리", one_liner="한줄",
                              prompt_template=StoryPromptTemplate.BASIC, setting_text=_SETTING))
    content.current_published_version_id = version.id
    novel.content_id, novel.content_type, novel.character_name = content.id, "story", None
    await db.flush()
    return novel


def _new_knowledge(snapshot: BibleSnapshot) -> tuple[uuid.UUID, ...]:
    """지식 칸이 비어 있으면 실패한다 — 지식 슬롯을 뺀 등록부에서 코어가 이 규칙을 건너뛰지 않으면 확정이 실패하게."""
    assert snapshot.knowledge is not None, "지식 슬롯이 없는 등록부에서 지식을 읽는 규칙이 돌았다"
    return tuple(row.id for row in snapshot.knowledge if row.id in snapshot.new_ids)


async def _projection(db: AsyncSession, novel_id: uuid.UUID) -> dict[str, list[tuple[Any, ...]]]:
    """슬롯별 항목을 소설과 무관한 꼴로 — 개체 id 는 (종류, 정규 이름). 연결 칸(사실의 시작 사건·앎의 알게 된 사건)은 빼고
    따로 본다. 안정 키는 개체 id 에서 나와 소설마다 다르므로 저장된 명제 칸으로 다시 계산한 키와 같은지만 본다."""
    names = {
        row.id: (row.kind, row.name_norm)
        for row in (await db.execute(
            select(NovelBibleEntity.id, NovelBibleEntity.kind, NovelBibleEntity.name_norm).where(
                NovelBibleEntity.novel_id == novel_id
            )
        )).all()
    }
    events = (await db.scalars(select(NovelBibleEvent).where(NovelBibleEvent.novel_id == novel_id))).all()
    facts = (await db.scalars(select(NovelBibleFact).where(NovelBibleFact.novel_id == novel_id))).all()
    knowledge = (await db.scalars(select(NovelBibleKnowledge).where(NovelBibleKnowledge.novel_id == novel_id))).all()
    assert all(row.fact_key == _proposition_key(row.proposition) for row in knowledge)

    def entity(value: str | None) -> tuple[str, str] | None:
        return names[uuid.UUID(value)] if value else None

    return {
        "events": sorted(
            (e.ordinal, e.summary, e.actuality, len(e.anchor_block_ids),
             sorted(names[i] for i in e.present_entity_ids)) for e in events
        ),
        "facts": sorted(
            (names[f.subject_entity_id], f.kind, f.predicate_norm, f.value_norm,
             names[f.value_entity_id] if f.value_entity_id else None, f.holds, f.onset, f.scope)
            for f in facts
        ),
        "knowledge": sorted(
            (names[k.knower_entity_id], k.kind, entity(k.proposition["subject_entity_id"]),
             k.proposition["kind"], k.proposition["predicate_norm"], k.proposition["value_norm"],
             entity(k.proposition["value_entity_id"]), k.proposition["holds"])
            for k in knowledge
        ),
    }


async def _count(db: AsyncSession, model: Any, **where: Any) -> int:
    statement = select(func.count()).select_from(model).filter_by(**where)
    return int(await db.scalar(statement) or 0)


@pytest.mark.parametrize("dropped", ["events", "facts", "knowledge", "source"])
async def test_dropping_a_slot_keeps_the_other_slots_rows_and_leaves_links_undetermined(
    db_session: AsyncSession, dropped: SlotId
) -> None:
    """같은 합성 화를 실제 등록부 전체와, 슬롯 하나를 뺀 부분집합으로 확정한다. 두 번 다 커밋되고, 남은 슬롯의 항목은 연결 칸을
    빼면 같으며, 뺀 슬롯의 작업·항목은 없다. 뺀 슬롯이 사건이면 사실·앎의 사건 칸이 미정(NULL)이고, 원작이면 각색 후보만 없다.
    뺀 슬롯을 읽는 규칙은 돌지 않는다(돌면 빈 지식 칸을 읽다 확정이 실패한다). 깨지는 시나리오: 한 슬롯이 다른 슬롯의
    행이나 출력에 기대면 그 슬롯을 뺄 때 남은 슬롯의 항목이 달라지거나 확정이 실패한다."""
    rules = [FakeRule(pick=_new_knowledge, severity="warning", rule="knowledge_source_unclear",
                      slots=frozenset({"knowledge"}))]
    full_ids: tuple[SlotId, ...] = ("events", "facts", "knowledge", "source")
    outcomes: dict[str, tuple[uuid.UUID, uuid.UUID]] = {}
    for label, slot_ids in [("full", full_ids), ("partial", tuple(s for s in full_ids if s != dropped))]:
        novel = await _story_novel(db_session)
        chapter, revision = await add_chapter(db_session, novel.id, 1, _INDEPENDENCE_BODY)
        commit_id = await _confirm_and_run(
            db_session, chapter, revision, ScriptedAdapter(_independence_outputs()), _registry(*slot_ids), rules
        )
        assert await _status(db_session, commit_id) == "committed"
        outcomes[label] = (novel.id, commit_id)

    full_novel, _ = outcomes["full"]
    partial_novel, partial_commit = outcomes["partial"]
    full = await _projection(db_session, full_novel)
    partial = await _projection(db_session, partial_novel)
    assert all(full[slot_id] for slot_id in ("events", "facts", "knowledge"))
    for slot_id in ("events", "facts", "knowledge"):
        assert partial[slot_id] == ([] if slot_id == dropped else full[slot_id])
    assert await _count(db_session, NovelBibleJob, commit_id=partial_commit, slot=dropped) == 0
    links = {
        *(await db_session.scalars(select(NovelBibleFact.valid_from_event_id).where(NovelBibleFact.novel_id == partial_novel))),
        *(await db_session.scalars(
            select(NovelBibleKnowledge.known_since_event_id).where(NovelBibleKnowledge.novel_id == partial_novel)
        )),
    }
    assert links == {None} if dropped == "events" else None not in links
    candidates = await _count(db_session, NovelBibleAdaptationCandidate, novel_id=partial_novel)
    assert candidates == (0 if dropped in ("source", "facts") else 1)
    assert await _count(db_session, NovelBibleAdaptationCandidate, novel_id=full_novel) == 1
    findings = await _count(db_session, NovelBibleFinding, novel_id=partial_novel)
    assert findings == (0 if dropped == "knowledge" else 1)


def test_the_registry_holds_the_knowledge_slot() -> None:
    assert isinstance(REGISTRY.extracting["knowledge"], KnowledgeSlot)
